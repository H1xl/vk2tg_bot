"""
Menu handlers: reply keyboard + native command menu
Обработчики меню: reply-клавиатура + нативное меню команд

This module wires the button UI on top of the existing command handlers:

* /menu shows a role-aware reply keyboard (utils/keyboards.py).
* Tapping a button sends its label; on_menu_button() routes the label to the
  matching command. Argument-less commands are dispatched to their existing
  @require_auth handlers (which enforce access themselves). Argument-taking
  actions reuse the interactive prompt system, with an explicit role check here
  because prompt_arg() does not authorize on its own.
* set_bot_commands() registers the native "Menu" button command list with
  Telegram, scoped so the permanent admin sees every command and everyone else
  sees only the public ones.

Меню-кнопки надстроены над существующими обработчиками команд: безаргументные
команды вызывают свои @require_auth-обработчики, а действия с аргументом
переиспользуют интерактивный запрос параметра (с проверкой роли здесь).
"""

from aiogram import F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    Message,
)

import config
from handlers.interactive import prompt_arg
from utils import keyboards as kb
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="menu_handlers")

router = Router()
auth_service = None


# =====
# /menu and /hide
# /menu и /hide
# =====


async def cmd_menu(message: Message):
    """Show the role-aware reply keyboard"""
    role, is_blocked = await auth_service.check_user_access(
        message.from_user.id, message.from_user.username
    )

    if is_blocked:
        await message.answer(Messages.CHANNELS_BLOCKED, parse_mode="HTML")
        return

    await message.answer(
        Messages.MENU_OPENED,
        parse_mode="HTML",
        reply_markup=kb.menu_keyboard_for_role(role),
    )
    logger.info("menu_opened", user_id=message.from_user.id, role=role)


async def cmd_hide(message: Message):
    """Hide the reply keyboard"""
    await message.answer(
        Messages.MENU_HIDDEN,
        parse_mode="HTML",
        reply_markup=kb.remove_keyboard(),
    )


# =====
# Button dispatch
# Диспетчеризация кнопок
# =====

# Lazily-imported command handlers (filled in setup_menu_handlers) so this module
# does not create import cycles with the handler packages.
# Лениво подключаемые обработчики (заполняются в setup_menu_handlers).
_handlers = {}


async def _run_command_handler(name: str, message: Message, state: FSMContext):
    """Invoke an existing command handler; it enforces its own authorization."""
    handler, needs_state = _handlers[name]
    if needs_state:
        await handler(message, state)
    else:
        await handler(message)


async def _run_prompt(message: Message, state: FSMContext, action_key: str, permanent: bool):
    """Authorize, then start the interactive prompt for an argument-taking action."""
    role, is_blocked = await auth_service.check_user_access(
        message.from_user.id, message.from_user.username
    )

    if is_blocked:
        await message.answer(Messages.NOT_AUTHORIZED, parse_mode="HTML")
        return

    if permanent:
        if role != "permanent_admin":
            await message.answer(Messages.PERMANENT_ADMIN_REQUIRED, parse_mode="HTML")
            return
    elif role not in ("permanent_admin", "temp_admin"):
        await message.answer(Messages.NOT_AUTHORIZED, parse_mode="HTML")
        return

    await prompt_arg(message, state, action_key)


async def on_menu_button(message: Message, state: FSMContext):
    """Route a tapped menu button to the matching command/action."""
    label = message.text

    # Argument-less commands -> existing handlers (they self-authorize)
    # Безаргументные команды -> существующие обработчики (сами проверяют доступ)
    command_buttons = {
        kb.BTN_CHANNELS: "channels",
        kb.BTN_REPORT: "report",
        kb.BTN_LOGIN: "login",
        kb.BTN_PAIRS: "pairs",
        kb.BTN_STATUS: "status",
        kb.BTN_ERRORS: "errors",
        kb.BTN_LOGS: "logs",
        kb.BTN_HELP: "help",
        kb.BTN_INVITE: "invite",
        kb.BTN_BANNED: "banned",
    }

    # Argument-taking actions -> interactive prompt. Value: (action_key, permanent_only)
    # Действия с аргументом -> интерактивный запрос. Значение: (ключ, только_главный_админ)
    prompt_buttons = {
        kb.BTN_CONNECT: ("connect", False),
        kb.BTN_ENABLE: ("enable", False),
        kb.BTN_DISABLE: ("disable", False),
        kb.BTN_DELETE: ("delete", False),
        kb.BTN_AVATAR: ("avatar", False),
        kb.BTN_BACKFILL: ("backfill", False),
        kb.BTN_BROADCAST: ("broadcast", False),
        kb.BTN_BAN: ("ban", True),
        kb.BTN_UNBAN: ("unban", True),
        kb.BTN_REVOKE: ("revoke", True),
    }

    if label == kb.BTN_HIDE:
        await cmd_hide(message)
        return

    if label in command_buttons:
        await _run_command_handler(command_buttons[label], message, state)
        return

    if label in prompt_buttons:
        action_key, permanent = prompt_buttons[label]
        await _run_prompt(message, state, action_key, permanent)
        return


# =====
# Native command menu ("Menu" button)
# Нативное меню команд (кнопка "Menu")
# =====

# Public commands — shown to everyone in the native menu.
# Публичные команды — видны всем в нативном меню.
PUBLIC_COMMANDS = [
    BotCommand(command="menu", description="🧭 Открыть меню кнопок"),
    BotCommand(command="channels", description="📋 Список активных каналов"),
    BotCommand(command="report", description="⚠️ Пожаловаться на пост"),
    BotCommand(command="login", description="🔑 Авторизоваться"),
    BotCommand(command="start", description="👋 О боте"),
]

# Full command set — shown to admins (scoped to their chat).
# Полный набор — для админов (привязан к их чату).
ADMIN_COMMANDS = PUBLIC_COMMANDS + [
    BotCommand(command="pairs", description="🗂️ Список пар"),
    BotCommand(command="connect", description="➕ Подключить VK-группу"),
    BotCommand(command="enable", description="▶️ Запустить пару"),
    BotCommand(command="disable", description="⏹️ Остановить пару"),
    BotCommand(command="delete", description="🗑️ Удалить пару"),
    BotCommand(command="avatar", description="🖼️ Обновить аватарку"),
    BotCommand(command="backfill", description="📥 Переслать прошлые посты"),
    BotCommand(command="broadcast", description="📢 Рассылка по каналам"),
    BotCommand(command="status", description="📊 Статус системы"),
    BotCommand(command="errors", description="⚠️ Последние ошибки"),
    BotCommand(command="logs", description="📄 Файл логов"),
    BotCommand(command="invite", description="🎫 Код приглашения"),
    BotCommand(command="banned", description="📜 Заблокированные"),
    BotCommand(command="help", description="❓ Справка по командам"),
]


async def set_bot_commands(bot):
    """
    Register the native command menu with Telegram.
    Public commands for everyone; full set scoped to the permanent admin's chat.
    Temporary admins use /menu (their chat scope is set on login).
    """
    try:
        await bot.set_my_commands(PUBLIC_COMMANDS, scope=BotCommandScopeDefault())

        if config.config.admin_user_id:
            await bot.set_my_commands(
                ADMIN_COMMANDS,
                scope=BotCommandScopeChat(chat_id=config.config.admin_user_id),
            )

        logger.info("bot_commands_set", admin_id=config.config.admin_user_id)
    except Exception as e:
        logger.warning("bot_commands_set_failed", error=str(e))


async def set_admin_commands_for_chat(bot, chat_id: int):
    """Give a chat (e.g. a freshly-logged-in temp admin) the full command menu."""
    try:
        await bot.set_my_commands(ADMIN_COMMANDS, scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info("admin_commands_set_for_chat", chat_id=chat_id)
    except Exception as e:
        logger.warning("admin_commands_set_failed", chat_id=chat_id, error=str(e))


async def reset_commands_for_chat(bot, chat_id: int):
    """Drop a chat back to the public command menu (e.g. on revoke/expiry)."""
    try:
        await bot.delete_my_commands(scope=BotCommandScopeChat(chat_id=chat_id))
        logger.info("commands_reset_for_chat", chat_id=chat_id)
    except Exception as e:
        logger.warning("commands_reset_failed", chat_id=chat_id, error=str(e))


# =====
# Setup
# Настройка
# =====


def setup_menu_handlers(dp, auth_svc):
    """Register menu handlers. Must run after the other handlers are set up."""
    global auth_service
    auth_service = auth_svc

    # Import command handlers here to avoid import cycles at module load time.
    # Импортируем обработчики здесь, чтобы избежать циклических импортов.
    from handlers.admin import cmd_blocklist, cmd_invite
    from handlers.auth import cmd_login
    from handlers.pair_management import cmd_list
    from handlers.system import cmd_errors, cmd_help, cmd_logs, cmd_status
    from handlers.user import cmd_channels, cmd_report

    _handlers.update(
        {
            "status": (cmd_status, False),
            "errors": (cmd_errors, False),
            "logs": (cmd_logs, False),
            "help": (cmd_help, False),
            "pairs": (cmd_list, False),
            "channels": (cmd_channels, False),
            "report": (cmd_report, True),
            "login": (cmd_login, True),
            "invite": (cmd_invite, False),
            "banned": (cmd_blocklist, False),
        }
    )

    router.message.register(cmd_menu, Command("menu", "m"))
    router.message.register(cmd_hide, Command("hide"))

    # Dispatch taps on known menu labels. Only fires outside an FSM state, so it
    # never swallows replies the bot is actively waiting for (login code, report
    # reason, pair-id prompt, etc.).
    # Срабатывает только вне FSM-состояния, чтобы не перехватывать ожидаемые ответы.
    all_labels = {
        kb.BTN_CHANNELS,
        kb.BTN_REPORT,
        kb.BTN_LOGIN,
        kb.BTN_PAIRS,
        kb.BTN_CONNECT,
        kb.BTN_ENABLE,
        kb.BTN_DISABLE,
        kb.BTN_DELETE,
        kb.BTN_AVATAR,
        kb.BTN_BACKFILL,
        kb.BTN_BROADCAST,
        kb.BTN_STATUS,
        kb.BTN_ERRORS,
        kb.BTN_LOGS,
        kb.BTN_HELP,
        kb.BTN_INVITE,
        kb.BTN_BAN,
        kb.BTN_UNBAN,
        kb.BTN_REVOKE,
        kb.BTN_BANNED,
        kb.BTN_HIDE,
    }
    router.message.register(on_menu_button, StateFilter(None), F.text.in_(all_labels))

    dp.include_router(router)
