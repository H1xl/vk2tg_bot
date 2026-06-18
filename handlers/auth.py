"""
Authentication handlers with invite codes
Обработчики аутентификации с кодами приглашения
"""

from functools import wraps

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message

from services.auth_service import AuthService
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="auth_handlers")

router = Router()
auth_service = None

# =====
# FSM States
# Состояния FSM
# =====


class AuthStates(StatesGroup):
    """States for authentication"""

    waiting_for_code = State()


# =====
# Authorization decorators
# Декораторы авторизации
# =====


def require_auth(func):
    """Require any authorization (permanent_admin, temp_admin) and not blocked"""

    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        user_id = message.from_user.id
        role, is_blocked = await auth_service.check_user_access(user_id, message.from_user.username)

        # Blocked users are denied even if they hold an admin role
        # Заблокированные пользователи не допускаются даже с ролью админа
        if is_blocked:
            await message.answer(Messages.NOT_AUTHORIZED, parse_mode="HTML")
            return

        if role in ["permanent_admin", "temp_admin"]:
            return await func(message, *args, **kwargs)

        await message.answer(Messages.NOT_AUTHORIZED, parse_mode="HTML")
        return

    return wrapper


def require_permanent_admin(func):
    """Require permanent admin rights"""

    @wraps(func)
    async def wrapper(message: Message, *args, **kwargs):
        user_id = message.from_user.id
        role, is_blocked = await auth_service.check_user_access(user_id, message.from_user.username)

        # Permanent admin can never be blocked (enforced in AuthService), but guard anyway.
        if is_blocked:
            await message.answer(Messages.PERMANENT_ADMIN_REQUIRED, parse_mode="HTML")
            return

        if role == "permanent_admin":
            return await func(message, *args, **kwargs)

        await message.answer(Messages.PERMANENT_ADMIN_REQUIRED, parse_mode="HTML")
        return

    return wrapper


# =====
# /login command
# Команда /login
# =====


async def cmd_login(message: Message, state: FSMContext):
    """Authorization via invite code"""
    user_id = message.from_user.id

    # Check current role / Проверяем текущую роль
    role, _ = await auth_service.check_user_access(user_id, message.from_user.username)

    if role in ["permanent_admin", "temp_admin"]:
        await message.answer(Messages.ALREADY_AUTHORIZED, parse_mode="HTML")
        return

    await message.answer(Messages.LOGIN_PROMPT, parse_mode="HTML")
    await state.set_state(AuthStates.waiting_for_code)

    logger.info("login_initiated", user_id=user_id)


# =====
# Handle invite code
# Обработка кода приглашения
# =====


async def handle_invite_code(message: Message, state: FSMContext):
    """Handle invite code input"""
    user_id = message.from_user.id
    code = message.text.strip()

    # Delete password message for security / Удаляем сообщение с кодом для безопасности
    try:
        await message.delete()
    except Exception:
        pass

    # Check code / Проверяем код
    success = await auth_service.use_invite_code(code, user_id, message.from_user.username)

    if success:
        # Give the new temp admin the full native command menu in their chat.
        # Выдаём новому временному админу полное нативное меню команд.
        from handlers.menu import set_admin_commands_for_chat

        await set_admin_commands_for_chat(message.bot, user_id)

        await message.answer(Messages.LOGIN_SUCCESS, parse_mode="HTML")
        logger.info("login_success", user_id=user_id)
    else:
        await message.answer(Messages.LOGIN_INVALID_CODE, parse_mode="HTML")
        logger.warning("login_failed", user_id=user_id)

    await state.clear()


# =====
# Cancel login
# Отмена логина
# =====


async def cancel_login(message: Message, state: FSMContext):
    """Cancel login process"""
    await state.clear()
    await message.answer(Messages.LOGIN_CANCELLED, parse_mode="HTML")
    logger.info("login_cancelled", user_id=message.from_user.id)


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_auth_handlers(dp, auth_svc):
    """Setup authentication handlers"""
    global auth_service
    auth_service = auth_svc

    router.message.register(cmd_login, Command("login"))
    # /cancel must be registered BEFORE the generic text handler, otherwise the
    # text handler treats "/cancel" as an invite code.
    # /cancel регистрируем РАНЬШЕ текстового обработчика, иначе "/cancel" уйдёт как код.
    router.message.register(
        cancel_login, Command("cancel"), StateFilter(AuthStates.waiting_for_code)
    )
    router.message.register(handle_invite_code, StateFilter(AuthStates.waiting_for_code), F.text)

    dp.include_router(router)
