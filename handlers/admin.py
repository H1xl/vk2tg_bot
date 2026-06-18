"""
Admin handlers for permanent admin only
Обработчики администрирования только для постоянного админа
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.auth import require_permanent_admin
from handlers.interactive import get_command_arg, prompt_arg, register_action
from services.auth_service import AuthService
from utils.helpers import escape_html
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="admin_handlers")

router = Router()
auth_service = None

# =====
# /invite - generate invite code
# /invite - генерация кода приглашения
# =====


@require_permanent_admin
async def cmd_invite(message: Message):
    """Generate invite code for temporary admin"""
    admin_id = message.from_user.id

    code = await auth_service.generate_invite_code(admin_id)

    await message.answer(Messages.INVITE_CODE_GENERATED.format(code=code), parse_mode="HTML")

    logger.info("invite_code_created", admin_id=admin_id, code=code)


# =====
# /revoke - revoke temporary admin rights
# /revoke - отзыв прав временного админа
# =====


@require_permanent_admin
async def cmd_revoke(message: Message, state: FSMContext):
    """Revoke temporary admin rights"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "revoke")
        return
    await _run_revoke(message, arg, state)


async def _run_revoke(message: Message, arg: str, state: FSMContext):
    user_input = arg.split()[0]

    target_user_id = await _parse_user_identifier(user_input, message.bot)

    if not target_user_id:
        await message.answer(Messages.INVALID_USER_ID, parse_mode="HTML")
        return

    success = await auth_service.revoke_temp_admin(target_user_id)

    if success:
        # Menu/keyboard reset for the revoked user is handled inside revoke_temp_admin.
        # Сброс меню/клавиатуры разжалованного пользователя выполняется в revoke_temp_admin.
        await message.answer(
            Messages.REVOKE_SUCCESS.format(
                user=await auth_service.get_user_mention(target_user_id)
            ),
            parse_mode="HTML",
        )
        logger.info(
            "temp_admin_revoked", admin_id=message.from_user.id, target_user_id=target_user_id
        )
    else:
        await message.answer(Messages.REVOKE_NOT_TEMP_ADMIN, parse_mode="HTML")


# =====
# /ban - block user
# /ban - блокировка пользователя
# =====


@require_permanent_admin
async def cmd_block(message: Message, state: FSMContext):
    """Block user (for reports)"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "ban")
        return
    await _run_ban(message, arg, state)


async def _run_ban(message: Message, arg: str, state: FSMContext):
    user_input = arg.split()[0]

    target_user_id = await _parse_user_identifier(user_input, message.bot)

    if not target_user_id:
        await message.answer(Messages.INVALID_USER_ID, parse_mode="HTML")
        return

    success = await auth_service.block_user(target_user_id)

    if not success:
        await message.answer(Messages.CANNOT_BLOCK_ADMIN, parse_mode="HTML")
        return

    await message.answer(
        Messages.BLOCK_SUCCESS.format(user=await auth_service.get_user_mention(target_user_id)),
        parse_mode="HTML",
    )

    logger.info("user_blocked", admin_id=message.from_user.id, target_user_id=target_user_id)


# =====
# /unban - unblock user
# /unban - разблокировка пользователя
# =====


@require_permanent_admin
async def cmd_unblock(message: Message, state: FSMContext):
    """Unblock user"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "unban")
        return
    await _run_unban(message, arg, state)


async def _run_unban(message: Message, arg: str, state: FSMContext):
    user_input = arg.split()[0]

    target_user_id = await _parse_user_identifier(user_input, message.bot)

    if not target_user_id:
        await message.answer(Messages.INVALID_USER_ID, parse_mode="HTML")
        return

    success = await auth_service.unblock_user(target_user_id)

    if success:
        await message.answer(
            Messages.UNBLOCK_SUCCESS.format(
                user=await auth_service.get_user_mention(target_user_id)
            ),
            parse_mode="HTML",
        )
        logger.info("user_unblocked", admin_id=message.from_user.id, target_user_id=target_user_id)
    else:
        await message.answer(Messages.USER_NOT_FOUND, parse_mode="HTML")


# =====
# /banned - show blocked users
# /banned - список заблокированных
# =====


@require_permanent_admin
async def cmd_blocklist(message: Message):
    """Show blocked users"""
    blocked_users = await auth_service.get_blocked_users()

    if not blocked_users:
        await message.answer(Messages.BLOCKLIST_EMPTY, parse_mode="HTML")
        return

    cards = []
    for user in blocked_users:
        if user.username:
            cards.append(
                Messages.BLOCKLIST_CARD_NAMED.format(
                    username=escape_html(f"@{user.username}"),
                    user_id=user.user_id,
                )
            )
        else:
            cards.append(Messages.BLOCKLIST_CARD_ID.format(user_id=user.user_id))

    text = Messages.BLOCKLIST_HEADER.format(count=len(blocked_users)) + "\n\n" + "\n\n".join(cards)

    await message.answer(text, parse_mode="HTML")

    logger.info("blocklist_viewed", admin_id=message.from_user.id, count=len(blocked_users))


# =====
# Helper: Parse user identifier (ID or @username)
# Помощник: Парсинг идентификатора пользователя (ID или @username)
# =====


async def _parse_user_identifier(user_input: str, bot) -> int:
    """
    Parse user identifier from input
    Supports: numeric ID, @username
    Returns: user_id or None
    """

    user_input = user_input.strip()

    if user_input.lstrip("-").isdigit():
        return int(user_input)

    if user_input.startswith("@"):
        username = user_input[1:]

        from database.models import User

        try:
            user = await User.filter(username=username).first()
            if user:
                return user.user_id
        except Exception as e:
            logger.warning("username_lookup_failed", username=username, error=str(e))

    return None


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_admin_handlers(dp, auth_svc):
    """Setup admin handlers"""
    global auth_service
    auth_service = auth_svc

    # Register interactive actions / Регистрация интерактивных действий
    register_action("revoke", _run_revoke, Messages.PROMPT_USER)
    register_action("ban", _run_ban, Messages.PROMPT_USER)
    register_action("unban", _run_unban, Messages.PROMPT_USER)

    router.message.register(cmd_invite, Command("invite", "inv"))
    router.message.register(cmd_revoke, Command("revoke", "rev"))
    router.message.register(cmd_block, Command("ban"))
    router.message.register(cmd_unblock, Command("unban"))
    router.message.register(cmd_blocklist, Command("banned", "bans"))

    dp.include_router(router)
