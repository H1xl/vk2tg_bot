"""
Pair management handlers with HTML formatting
Обработчики управления парами с HTML форматированием
"""

import asyncio
import random
import shlex
import string
from datetime import datetime
from math import ceil
from typing import Dict

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

import config
from handlers.auth import require_auth
from handlers.interactive import get_command_arg, prompt_arg, register_action
from utils.helpers import (
    calculate_image_hash,
    escape_html,
    generate_next_pair_id,
    generate_unique_pair_id,
)
from utils.logger import logger
from utils.messages import Messages
from utils.validators import validate_is_safe, validate_pair_id, validate_pair_name, validate_vk_id

router = Router()
vk_service = None
telegram_service = None
storage_service = None
media_handler = None

# =====
# Pair verification storage with automatic cleanup
# Хранилище верификации пар с автоматической очисткой
# =====

_pair_verifications: Dict[int, Dict] = {}
_cleanup_task = None


async def _cleanup_expired_verifications():
    """Periodically cleanup expired verifications"""
    while True:
        try:
            await asyncio.sleep(60)  # Проверка каждую минуту

            current_time = asyncio.get_event_loop().time()
            expired_users = []

            for user_id, data in _pair_verifications.items():
                if (
                    current_time - data.get("started_at", 0)
                    > config.config.pair_verification_timeout
                ):
                    expired_users.append(user_id)

            for user_id in expired_users:
                del _pair_verifications[user_id]
                logger.debug("verification_expired_cleanup", user_id=user_id)

            if expired_users:
                logger.info("verification_cleanup", count=len(expired_users))

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("verification_cleanup_error", error=str(e))


def start_verification_cleanup():
    """Start background cleanup task"""
    global _cleanup_task
    if _cleanup_task is None:
        _cleanup_task = asyncio.create_task(_cleanup_expired_verifications())
        logger.info("verification_cleanup_started")


def stop_verification_cleanup():
    """Stop background cleanup task"""
    global _cleanup_task
    if _cleanup_task:
        _cleanup_task.cancel()
        _cleanup_task = None
        logger.info("verification_cleanup_stopped")


# =====
# FSM States
# Состояния FSM
# =====


class PairStates(StatesGroup):
    """States for pair creation"""

    waiting_for_channel_forward = State()


async def _safe_delete(msg):
    """Delete a message ignoring errors"""
    try:
        await msg.delete()
    except Exception:
        pass


# =====
# /connect command with improved argument parsing
# Команда /connect с улучшенным парсингом аргументов
# =====


@require_auth
async def cmd_pair(message: Message, state: FSMContext):
    """Create pair with verification (prompts for the VK link if omitted)"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "connect")
        return
    await _start_connect(message, arg, state)


async def _start_connect(message: Message, arg: str, state: FSMContext):
    """Begin pair creation from the argument string (without the command token)"""

    # Parse arguments using shlex for proper quote handling
    # Парсинг аргументов с помощью shlex для правильной обработки кавычек
    try:
        args = shlex.split(arg)
    except ValueError as e:
        await message.answer(
            Messages.PAIR_COMMAND_PARSE_ERROR.format(error=escape_html(str(e))), parse_mode="HTML"
        )
        logger.warning("pair_command_parse_error", user_id=message.from_user.id, error=str(e))
        return

    if len(args) < 1:
        await message.answer(Messages.PAIR_USAGE, parse_mode="HTML")
        return

    vk_input = args[0]
    is_safe_input = args[1] if len(args) > 1 else "false"
    pair_name = args[2] if len(args) > 2 else ""
    custom_pair_id = args[3] if len(args) > 3 else None

    # Validate is_safe
    is_safe = validate_is_safe(is_safe_input)
    if is_safe is None:
        await message.answer(Messages.PAIR_INVALID_IS_SAFE, parse_mode="HTML")
        return

    # Validate inputs / Валидация входных данных
    if pair_name and not validate_pair_name(pair_name):
        await message.answer(Messages.PAIR_NAME_TOO_LONG, parse_mode="HTML")
        return

    if custom_pair_id and not validate_pair_id(custom_pair_id):
        await message.answer(Messages.PAIR_INVALID_ID_FORMAT, parse_mode="HTML")
        return

    # Validate VK
    vk_screen_name = validate_vk_id(vk_input)
    if not vk_screen_name:
        await message.answer(Messages.PAIR_INVALID_VK_ID, parse_mode="HTML")
        return

    # Get VK group ID / Получить ID группы VK
    processing_msg = await message.answer(Messages.PAIR_VK_GROUP_FETCH, parse_mode="HTML")

    if vk_screen_name.isdigit():
        vk_id = int(vk_screen_name)
    else:
        vk_id = await vk_service.get_group_id(vk_screen_name)
        if not vk_id:
            await _safe_delete(processing_msg)
            await message.answer(Messages.PAIR_VK_GROUP_NOT_FOUND, parse_mode="HTML")
            return

    # Validate VK access / Валидация доступа VK
    await processing_msg.edit_text(Messages.PAIR_VK_ACCESS_CHECK, parse_mode="HTML")

    if not await vk_service.validate_group_access(vk_id):
        await _safe_delete(processing_msg)
        await message.answer(Messages.PAIR_VK_NO_ACCESS, parse_mode="HTML")
        return

    # Reject early if this VK group is already connected to an existing pair
    # (one VK group must not be linked twice).
    # Отклоняем, если эта VK-группа уже подключена к существующей паре.
    existing_pairs = await storage_service.get_all_pairs()
    duplicate = next((p for p in existing_pairs if p.vk_id == vk_id), None)
    if duplicate:
        await _safe_delete(processing_msg)
        await message.answer(
            Messages.PAIR_VK_ALREADY_CONNECTED.format(pair_id=duplicate.id), parse_mode="HTML"
        )
        logger.info(
            "pair_creation_duplicate_vk",
            user_id=message.from_user.id,
            vk_id=vk_id,
            existing_pair=duplicate.id,
        )
        return

    # Generate verification code / Генерация кода верификации
    verification_code = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

    # Store verification data / Сохранить данные верификации
    user_id = message.from_user.id
    _pair_verifications[user_id] = {
        "code": verification_code,
        "vk_id": vk_id,
        "pair_name": pair_name,
        "custom_pair_id": custom_pair_id,
        "is_safe": is_safe,
        "started_at": asyncio.get_event_loop().time(),
    }

    await processing_msg.delete()

    timeout_minutes = config.config.pair_verification_timeout // 60

    await message.answer(
        Messages.PAIR_VERIFICATION_PROMPT.format(code=verification_code, timeout=timeout_minutes),
        parse_mode="HTML",
    )

    await state.set_state(PairStates.waiting_for_channel_forward)

    logger.info("pair_creation_initiated", user_id=user_id, vk_id=vk_id)


# =====
# Handle forwarded message with verification code
# Обработка пересланного сообщения с кодом верификации
# =====


async def handle_pair_forward(message: Message, state: FSMContext):
    """Handle forwarded message for pair verification"""
    user_id = message.from_user.id

    # Check if verification exists / Проверка существования верификации
    if user_id not in _pair_verifications:
        await message.answer(Messages.PAIR_VERIFICATION_NOT_FOUND, parse_mode="HTML")
        return

    # Check that message is forwarded from channel / Проверка что сообщение из канала
    if not message.forward_from_chat or message.forward_from_chat.type != "channel":
        await message.answer(Messages.PAIR_FORWARD_FROM_CHANNEL_ONLY, parse_mode="HTML")
        return

    # Get verification data / Получить данные верификации
    verification = _pair_verifications[user_id]
    expected_code = verification["code"]

    # Check code in text / Проверка кода в тексте
    if not message.text or expected_code not in message.text:
        await message.answer(
            Messages.PAIR_CODE_NOT_FOUND.format(code=expected_code), parse_mode="HTML"
        )
        return

    # Get channel ID / Получить ID канала
    channel_id = message.forward_from_chat.id
    channel_title = message.forward_from_chat.title or Messages.UNKNOWN_TITLE

    processing_msg = await message.answer(
        Messages.PAIR_CHANNEL_ACCESS_CHECK.format(title=escape_html(channel_title)),
        parse_mode="HTML",
    )

    # Validate access / Валидация доступа
    can_access = await telegram_service.validate_channel_access(channel_id)

    if not can_access:
        await message.answer(Messages.PAIR_NO_CHANNEL_ACCESS, parse_mode="HTML")
        await state.clear()
        del _pair_verifications[user_id]
        return

    # Create pair / Создать пару
    try:
        vk_id = verification["vk_id"]
        pair_name = verification["pair_name"]
        custom_pair_id = verification["custom_pair_id"]
        is_safe = verification["is_safe"]

        # Generate pair_id if not provided / Генерация pair_id если не предоставлен
        if not custom_pair_id:
            all_pairs = await storage_service.get_all_pairs()
            existing_ids = [p.id for p in all_pairs]
            custom_pair_id = generate_next_pair_id(existing_ids)

        # Try to create pair (with race condition protection)
        # Попытка создать пару (с защитой от race condition)
        try:
            pair = await storage_service.create_pair(
                custom_pair_id, vk_id, channel_id, pair_name, is_safe
            )
        except ValueError:
            # Race condition: ID already exists, generate UUID
            # Race condition: ID уже существует, генерируем UUID
            logger.warning("pair_id_conflict", pair_id=custom_pair_id, user_id=user_id)
            custom_pair_id = generate_unique_pair_id()
            pair = await storage_service.create_pair(
                custom_pair_id, vk_id, channel_id, pair_name, is_safe
            )

        # Get last post ID / Получить ID последнего поста
        posts = await vk_service.get_posts(vk_id, count=1)
        if posts and len(posts) > 0:
            last_post_id = posts[0].get("id")
            await storage_service.set_last_post(pair.id, last_post_id)

        # Update channel avatar from VK / Обновить аватарку канала из VK
        try:
            await _update_channel_avatar_initial(pair, message.bot)
        except Exception as e:
            logger.warning("initial_avatar_update_failed", pair_id=pair.id, error=str(e))

        # Remove verification / Удалить верификацию
        del _pair_verifications[user_id]
        await state.clear()

        await processing_msg.delete()

        safety_mode = Messages.PAIR_SAFE_TRUSTED if is_safe else Messages.PAIR_SAFE_CHECKED

        await message.answer(
            Messages.PAIR_CREATED.format(
                title=escape_html(channel_title),
                pair_id=pair.id,
                name=escape_html(pair.name) if pair.name else Messages.NO_NAME,
                safety=safety_mode,
                pair_id_activate=pair.id,
            ),
            parse_mode="HTML",
        )

        logger.info("pair_created", pair_id=pair.id, vk_id=vk_id, tg_id=channel_id, is_safe=is_safe)

    except ValueError as e:
        await message.answer(
            Messages.PAIR_ALREADY_EXISTS.format(error=escape_html(str(e))), parse_mode="HTML"
        )
        await state.clear()
        if user_id in _pair_verifications:
            del _pair_verifications[user_id]
    except Exception as e:
        logger.error("pair_creation_error", error=str(e))
        await message.answer(
            Messages.PAIR_CREATION_ERROR.format(error=escape_html(str(e))), parse_mode="HTML"
        )
        await state.clear()
        if user_id in _pair_verifications:
            del _pair_verifications[user_id]


async def _update_channel_avatar_initial(pair, bot):
    """Update channel avatar on pair creation"""
    try:
        # Get VK group avatar / Получить аватар группы VK
        avatar_url = await vk_service.get_group_photo(pair.vk_id, size="photo_200")

        if not avatar_url:
            logger.warning("initial_avatar_vk_not_found", pair_id=pair.id)
            return

        # Download avatar / Скачать аватар
        avatar_path = await media_handler.download_photo(
            avatar_url, f"avatar_{pair.vk_id}_initial.jpg"
        )

        if not avatar_path:
            logger.warning("initial_avatar_download_failed", pair_id=pair.id)
            return

        try:
            # Calculate hash / Вычислить хэш
            avatar_hash = await calculate_image_hash(avatar_path)

            if not avatar_hash:
                logger.warning("initial_avatar_hash_failed", pair_id=pair.id)
                return

            # Update Telegram channel avatar / Обновить аватар канала Telegram
            success = await telegram_service.update_channel_avatar(pair.tg_id, avatar_path)

            if success:
                # Save hash in database / Сохранить хэш в БД
                await storage_service.update_avatar_info(pair.id, avatar_hash)
                logger.info("initial_avatar_updated", pair_id=pair.id)
            else:
                logger.warning("initial_avatar_tg_update_failed", pair_id=pair.id)

        finally:
            # Cleanup downloaded file / Очистить скачанный файл
            await media_handler.cleanup_file(avatar_path)

    except Exception as e:
        logger.error("initial_avatar_update_error", pair_id=pair.id, error=str(e))


# =====
# Cancel pair creation
# Отмена создания пары
# =====


async def cancel_pair(message: Message, state: FSMContext):
    """Cancel pair creation process"""
    user_id = message.from_user.id

    await state.clear()
    if user_id in _pair_verifications:
        del _pair_verifications[user_id]

    await message.answer(Messages.PAIR_CREATION_CANCELLED, parse_mode="HTML")
    logger.info("pair_creation_cancelled", user_id=user_id)


# =====
# List command with improved UI
# Команда списка с улучшенным UI
# =====


@require_auth
async def cmd_list(message: Message):
    """List all pairs with pagination and improved readability"""
    args = message.text.split()
    page = int(args[1]) if len(args) > 1 and args[1].isdigit() else 1

    all_pairs = await storage_service.get_all_pairs()

    if not all_pairs:
        await message.answer(Messages.LIST_EMPTY, parse_mode="HTML")
        return

    # Sort by creation date / Сортировка по дате создания
    all_pairs.sort(key=lambda x: x.created_at, reverse=True)

    # Pagination / Пагинация
    per_page = config.config.pairs_per_page
    total_pages = ceil(len(all_pairs) / per_page)
    page = max(1, min(page, total_pages))

    start_idx = (page - 1) * per_page
    end_idx = start_idx + per_page
    page_pairs = all_pairs[start_idx:end_idx]

    # Build a card per pair (proportional font, no truncation / horizontal scroll)
    # Карточка на пару (пропорциональный шрифт, без обрезки и горизонтального скролла)
    cards = []
    for pair in page_pairs:
        status = (
            Messages.PAIR_STATUS_ACTIVE if pair.status == "active" else Messages.PAIR_STATUS_STOPPED
        )
        safety = Messages.PAIR_SAFE_TRUSTED if pair.is_safe else Messages.PAIR_SAFE_CHECKED
        cards.append(
            Messages.LIST_CARD.format(
                status=status,
                name=escape_html(pair.name or Messages.NO_NAME),
                vk_id=escape_html(pair.vk_id),
                safety=safety,
                pair_id=escape_html(pair.id),
            )
        )

    output = (
        Messages.LIST_HEADER.format(page=page, total_pages=total_pages)
        + "\n\n"
        + "\n\n".join(cards)
    )

    # Add navigation hint / Добавить подсказку навигации
    if total_pages > 1:
        nav_hint = "\n\n" + Messages.LIST_NAVIGATION

        if page > 1:
            nav_hint += f"<code>/pairs {page - 1}</code> ← "
        nav_hint += "<code>/pairs &lt;номер&gt;</code>"
        if page < total_pages:
            nav_hint += f" → <code>/pairs {page + 1}</code>"

        output += nav_hint

    await message.answer(output, parse_mode="HTML")
    logger.debug("list_displayed", user_id=message.from_user.id, page=page, total_pages=total_pages)


# =====
# Remove command
# Команда удаления
# =====


@require_auth
async def cmd_remove(message: Message, state: FSMContext):
    """Remove pair"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "delete")
        return
    await _run_delete(message, arg, state)


async def _run_delete(message: Message, arg: str, state: FSMContext):
    identifier = arg.strip()

    # Try to find by ID first / Попытка найти по ID сначала
    pair = await storage_service.get_pair_by_id(identifier)

    if not pair:
        await message.answer(
            Messages.PAIR_NOT_FOUND.format(pair_id=escape_html(identifier)), parse_mode="HTML"
        )
        return

    # Remove pair / Удалить пару
    pair_id = pair.id
    vk_id = pair.vk_id
    success = await storage_service.remove_pair(pair_id, vk_id)

    if success:
        await message.answer(Messages.PAIR_REMOVED.format(pair_id=pair_id), parse_mode="HTML")
        logger.info("pair_removed", pair_id=pair_id, user_id=message.from_user.id)
    else:
        await message.answer(Messages.PAIR_REMOVE_FAILED, parse_mode="HTML")


# =====
# Activate command
# Команда активации
# =====


@require_auth
async def cmd_activate(message: Message, state: FSMContext):
    """Activate pair"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "enable")
        return
    await _run_enable(message, arg, state)


async def _run_enable(message: Message, arg: str, state: FSMContext):
    pair_id = arg.split()[0]
    success = await storage_service.update_pair_status(pair_id, "active")

    if success:
        await message.answer(Messages.PAIR_ACTIVATED.format(pair_id=pair_id), parse_mode="HTML")
        logger.info("pair_activated", pair_id=pair_id, user_id=message.from_user.id)
    else:
        await message.answer(Messages.PAIR_NOT_FOUND.format(pair_id=pair_id), parse_mode="HTML")


# =====
# Stop command
# Команда остановки
# =====


@require_auth
async def cmd_stop(message: Message, state: FSMContext):
    """Stop pair"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "disable")
        return
    await _run_disable(message, arg, state)


async def _run_disable(message: Message, arg: str, state: FSMContext):
    pair_id = arg.split()[0]
    success = await storage_service.update_pair_status(pair_id, "stopped")

    if success:
        await message.answer(Messages.PAIR_STOPPED.format(pair_id=pair_id), parse_mode="HTML")
        logger.info("pair_stopped", pair_id=pair_id, user_id=message.from_user.id)
    else:
        await message.answer(Messages.PAIR_NOT_FOUND.format(pair_id=pair_id), parse_mode="HTML")


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_pair_handlers(dp, bot, vk_svc, telegram_svc, storage_svc, media_hdl):
    """Setup pair management handlers with shared service instances"""
    global vk_service, telegram_service, storage_service, media_handler

    # Use shared services / Используем общие сервисы
    vk_service = vk_svc
    telegram_service = telegram_svc
    storage_service = storage_svc
    media_handler = media_hdl

    # Register interactive actions / Регистрация интерактивных действий
    register_action("connect", _start_connect, Messages.PROMPT_CONNECT)
    register_action("enable", _run_enable, Messages.PROMPT_PAIR_ID)
    register_action("disable", _run_disable, Messages.PROMPT_PAIR_ID)
    register_action("delete", _run_delete, Messages.PROMPT_PAIR_ID_OR_NAME)

    # Start verification cleanup task / Запуск задачи очистки верификаций
    start_verification_cleanup()

    router.message.register(cmd_pair, Command("connect", "con"))
    router.message.register(cmd_list, Command("pairs", "ls"))
    router.message.register(cmd_remove, Command("delete", "del"))
    router.message.register(cmd_activate, Command("enable", "on"))
    router.message.register(cmd_stop, Command("disable", "off"))

    # Cancel handler — registered BEFORE the catch-all forward handler so "/cancel"
    # is not consumed as a (non-channel) forward.
    # Отмена — раньше перехватчика пересылки, иначе "/cancel" уйдёт как пересылка.
    router.message.register(
        cancel_pair, Command("cancel"), StateFilter(PairStates.waiting_for_channel_forward)
    )

    # Catch ANY forwarded message during verification (forward_date covers forwards from
    # channels, chats AND private users), so a forward from a personal chat gets a helpful
    # reply instead of silence. Non-forward messages (e.g. other commands) pass through.
    # Ловим любую пересылку на шаге верификации (в т.ч. из лички); команды проходят дальше.
    router.message.register(
        handle_pair_forward, StateFilter(PairStates.waiting_for_channel_forward), F.forward_date
    )

    dp.include_router(router)
