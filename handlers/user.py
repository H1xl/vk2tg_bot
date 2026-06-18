"""
User handlers for reports and channels list
Обработчики пользователей для репортов и списка каналов
"""

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

import config
from services.auth_service import AuthService
from services.storage_service import StorageService
from utils.helpers import escape_html
from utils.link_formatter import link_formatter
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="user_handlers")

router = Router()
auth_service = None
storage_service = None

_report_timestamps = defaultdict(list)
_user_command_timestamps = defaultdict(list)
_last_error_messages = {}
_ERROR_COOLDOWN = 5

# =====
# FSM States for report
# Состояния FSM для репорта
# =====


class ReportStates(StatesGroup):
    """States for /report"""

    waiting_for_reason = State()
    waiting_for_forward = State()


# =====
# Rate limiting helper
# Помощник ограничения частоты
# =====


def check_rate_limit(
    user_id: int, limit: int, period_minutes: int, timestamps_dict: dict
) -> tuple[bool, int]:
    """
    Check if user exceeded rate limit
    Returns: (is_allowed, minutes_to_wait)
    """
    now = datetime.now()
    cutoff = now - timedelta(minutes=period_minutes)

    # Use .get() so checking an unknown user doesn't auto-create an empty key,
    # and drop the key entirely once its window is empty (no unbounded growth).
    # Через .get(), чтобы не плодить пустые ключи, и удаляем ключ при пустом окне.
    fresh = [ts for ts in timestamps_dict.get(user_id, []) if ts > cutoff]
    if fresh:
        timestamps_dict[user_id] = fresh
    else:
        timestamps_dict.pop(user_id, None)

    if len(fresh) >= limit:
        oldest = fresh[0]
        minutes_left = (
            int((oldest + timedelta(minutes=period_minutes) - now).total_seconds() / 60) + 1
        )
        return (False, minutes_left)

    return (True, 0)


def should_send_error(user_id: int, error_key: str) -> bool:
    """
    Check if error message should be sent (prevents spam)
    Returns: True if should send, False if cooldown active
    """
    now = datetime.now()
    key = f"{user_id}_{error_key}"

    # Prune entries older than the cooldown so the dict can't grow unbounded.
    # After pruning, any remaining key is, by definition, still within cooldown.
    # Чистим протухшие записи: после чистки оставшиеся ключи ещё в кулдауне.
    cutoff = now - timedelta(seconds=_ERROR_COOLDOWN)
    for k in [k for k, t in _last_error_messages.items() if t < cutoff]:
        del _last_error_messages[k]

    if key in _last_error_messages:
        return False

    _last_error_messages[key] = now
    return True


# =====
# /report command
# Команда /report
# =====


async def cmd_report(message: Message, state: FSMContext):
    """Start report process"""
    user_id = message.from_user.id

    role, is_blocked = await auth_service.check_user_access(user_id, message.from_user.username)

    if is_blocked:
        await message.answer(Messages.REPORT_BLOCKED, parse_mode="HTML")
        logger.info("report_blocked_user", user_id=user_id)
        return

    is_allowed, minutes_left = check_rate_limit(
        user_id, config.config.report_rate_limit_per_hour, 60, _report_timestamps
    )

    if not is_allowed:
        await message.answer(
            Messages.REPORT_RATE_LIMIT.format(minutes=minutes_left), parse_mode="HTML"
        )
        logger.info("report_rate_limited", user_id=user_id, minutes_left=minutes_left)
        return

    await message.answer(Messages.REPORT_ENTER_REASON, parse_mode="HTML")
    await state.set_state(ReportStates.waiting_for_reason)

    logger.info("report_initiated", user_id=user_id)


# =====
# Handle report reason
# Обработка причины жалобы
# =====


async def handle_report_reason(message: Message, state: FSMContext):
    """Handle report reason input"""
    user_id = message.from_user.id
    reason = message.text.strip()

    try:
        await message.delete()
    except Exception:
        pass

    if len(reason) > 500:
        if should_send_error(user_id, "report_reason_too_long"):
            await message.answer(Messages.REPORT_REASON_TOO_LONG, parse_mode="HTML")
        return

    if len(reason) < 10:
        if should_send_error(user_id, "report_reason_too_short"):
            await message.answer(Messages.REPORT_REASON_TOO_SHORT, parse_mode="HTML")
        return

    await state.update_data(reason=reason)

    await message.answer(Messages.REPORT_FORWARD_POST, parse_mode="HTML")
    await state.set_state(ReportStates.waiting_for_forward)

    logger.info("report_reason_received", user_id=user_id)


# =====
# Handle forwarded message
# Обработка пересланного сообщения
# =====


async def handle_report_forward(message: Message, state: FSMContext):
    """Handle forwarded message"""
    user_id = message.from_user.id
    username = message.from_user.username
    user_full_name = message.from_user.full_name

    if not message.forward_from_chat or message.forward_from_chat.type != "channel":
        if should_send_error(user_id, "report_not_from_channel"):
            await message.answer(Messages.REPORT_NOT_FROM_CHANNEL, parse_mode="HTML")
        return

    channel_id = message.forward_from_chat.id
    channel_title = message.forward_from_chat.title or Messages.UNKNOWN_TITLE
    channel_username = message.forward_from_chat.username
    message_id = message.forward_from_message_id

    pairs = await storage_service.get_all_pairs()
    pairs_by_tg_id = {p.tg_id: p for p in pairs}
    pair = pairs_by_tg_id.get(channel_id)

    if not pair:
        await message.answer(Messages.REPORT_UNKNOWN_CHANNEL, parse_mode="HTML")
        await state.clear()
        logger.info("report_unknown_channel", user_id=user_id, channel_id=channel_id)
        return

    data = await state.get_data()
    reason = data.get("reason", "")

    try:
        user_link = link_formatter.format_user_link(user_id, username, user_full_name)
        channel_link = link_formatter.format_channel_link(
            channel_id, channel_title, channel_username
        )

        report_text = Messages.REPORT_TO_CHANNEL.format(
            user_link=user_link,
            user_id=user_id,
            channel_link=channel_link,
            pair_id=pair.id,
            reason=escape_html(reason),
        )

        if not config.config.report_channel_id:
            logger.error("report_channel_not_configured", user_id=user_id)
            await message.answer(Messages.REPORT_CHANNEL_NOT_CONFIGURED, parse_mode="HTML")
            await state.clear()
            return

        await message.bot.send_message(
            config.config.report_channel_id, report_text, parse_mode="HTML"
        )

        try:
            await message.forward(config.config.report_channel_id)
            logger.info("report_post_forwarded", user_id=user_id, pair_id=pair.id)
        except Exception as e:
            logger.warning("report_post_forward_failed", user_id=user_id, error=str(e))

        _report_timestamps[user_id].append(datetime.now())

        await message.answer(Messages.REPORT_SUCCESS, parse_mode="HTML")
        logger.info("report_sent", user_id=user_id, pair_id=pair.id, channel_id=channel_id)

    except Exception as e:
        error_msg = str(e)
        logger.error("report_send_failed", user_id=user_id, error=error_msg)

        await message.answer(Messages.REPORT_SEND_FAILED, parse_mode="HTML")

    await state.clear()


# =====
# Cancel report
# Отмена репорта
# =====


async def cancel_report(message: Message, state: FSMContext):
    """Cancel report process"""
    await state.clear()
    await message.answer(Messages.REPORT_CANCELLED, parse_mode="HTML")
    logger.info("report_cancelled", user_id=message.from_user.id)


# =====
# /channels command with rate limiting
# Команда /channels с ограничением частоты
# =====


async def cmd_channels(message: Message):
    """Show list of active channels"""
    user_id = message.from_user.id

    role, is_blocked = await auth_service.check_user_access(user_id, message.from_user.username)

    if is_blocked:
        await message.answer(Messages.CHANNELS_BLOCKED, parse_mode="HTML")
        logger.info("channels_blocked_user", user_id=user_id)
        return

    if role not in ["permanent_admin", "temp_admin"]:
        is_allowed, minutes_left = check_rate_limit(
            user_id, config.config.user_commands_rate_limit, 1, _user_command_timestamps
        )

        if not is_allowed:
            await message.answer(
                Messages.CHANNELS_RATE_LIMIT.format(minutes=minutes_left), parse_mode="HTML"
            )
            logger.info("channels_rate_limited", user_id=user_id, minutes_left=minutes_left)
            return

        _user_command_timestamps[user_id].append(datetime.now())

    active_pairs = await storage_service.get_active_pairs()

    if not active_pairs:
        await message.answer(Messages.CHANNELS_EMPTY, parse_mode="HTML")
        return

    from services.telegram_service import TelegramService

    tg_service = TelegramService(message.bot)

    # Fetch channel titles in parallel / Параллельно получаем названия каналов
    channel_info_map = {}
    results = await asyncio.gather(
        *[tg_service.get_channel_info(pair.tg_id) for pair in active_pairs], return_exceptions=True
    )
    for pair, result in zip(active_pairs, results):
        if isinstance(result, Exception):
            logger.warning("channel_info_fetch_failed", pair_id=pair.id, error=str(result))
        elif result:
            channel_info_map[pair.tg_id] = result

    # Build a card per channel (proportional font, no truncation / horizontal scroll)
    # Карточка на канал (пропорциональный шрифт, без обрезки и горизонтального скролла)
    cards = []
    for pair in active_pairs:
        info = channel_info_map.get(pair.tg_id)
        title = (info.get("title") if info else None) or pair.name or Messages.NO_NAME
        username = info.get("username") if info else None
        # Link to the channel when it has a public @username; otherwise just its name
        # (private channels have no public link).
        # Ссылка на канал при наличии @username; иначе — просто название (у приватных ссылки нет).
        if username:
            channel = f'<a href="https://t.me/{username}">{escape_html(title)}</a>'
        else:
            # Private channel: no public @username, so no link — mark it as private.
            # Приватный канал: нет публичного @username и ссылки — помечаем как приватный.
            channel = f"<b>{escape_html(title)}</b>{Messages.CHANNELS_PRIVATE_SUFFIX}"
        posts_24h = await storage_service.get_posts_24h(pair.id)
        cards.append(Messages.CHANNELS_CARD.format(channel=channel, posts=posts_24h))

    text = Messages.CHANNELS_HEADER.format(count=len(active_pairs)) + "\n\n" + "\n\n".join(cards)

    await message.answer(text, parse_mode="HTML")
    logger.info("channels_list_viewed", user_id=user_id, count=len(active_pairs))


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_user_handlers(dp, auth_svc, storage_svc):
    """Setup user handlers"""
    global auth_service, storage_service
    auth_service = auth_svc
    storage_service = storage_svc

    router.message.register(cmd_report, Command("report", "rep"))
    router.message.register(cmd_channels, Command("channels", "ch"))

    # /cancel must be registered BEFORE the state catch-all handlers below,
    # otherwise "/cancel" is consumed as the report reason / forward.
    # /cancel — раньше перехватчиков состояния, иначе "/cancel" уйдёт как причина/пересылка.
    router.message.register(
        cancel_report,
        Command("cancel"),
        StateFilter(ReportStates.waiting_for_reason, ReportStates.waiting_for_forward),
    )

    router.message.register(
        handle_report_reason, StateFilter(ReportStates.waiting_for_reason), F.text
    )

    # Catch ANY forwarded message (forward_date is set for forwards from channels,
    # chats AND private users), so a forward from a personal chat gets a helpful reply
    # instead of silence. Non-forward messages (e.g. other commands) still pass through.
    # Ловим любую пересылку (в т.ч. из лички), чтобы она не игнорировалась; команды проходят дальше.
    router.message.register(
        handle_report_forward, StateFilter(ReportStates.waiting_for_forward), F.forward_date
    )

    dp.include_router(router)
