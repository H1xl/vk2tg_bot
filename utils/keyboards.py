"""
Keyboard builders for the bot UI
Конструкторы клавиатур для интерфейса бота

Two button surfaces are provided:

1. Reply keyboard (`/menu`) — persistent buttons under the input field.
   Tapping a button sends its label as a normal message; the dispatcher in
   handlers/menu.py routes the label to the matching command. Argument-taking
   actions reuse the interactive prompt system (handlers/interactive.py).

2. Native command menu (the blue "Menu" button) — configured via
   bot.set_my_commands() in handlers/menu.py.

Button labels are defined here as constants so the keyboard layout and the
dispatcher can never drift apart.
Метки кнопок определены здесь как константы, чтобы раскладка клавиатуры и
диспетчер не рассинхронизировались.
"""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, ReplyKeyboardRemove

# =====
# Button labels
# Метки кнопок
# =====

# Public / Публичные
BTN_CHANNELS = "📋 Каналы"
BTN_REPORT = "⚠️ Пожаловаться"
BTN_LOGIN = "🔑 Войти"

# Pair management / Управление парами
BTN_PAIRS = "🗂️ Пары"
BTN_CONNECT = "➕ Подключить"
BTN_ENABLE = "▶️ Запустить"
BTN_DISABLE = "⏹️ Остановить"
BTN_DELETE = "🗑️ Удалить"
BTN_AVATAR = "🖼️ Аватар"

# Actions / Действия
BTN_BACKFILL = "📥 Бэкфилл"
BTN_BROADCAST = "📢 Рассылка"

# System / Система
BTN_STATUS = "📊 Статус"
BTN_ERRORS = "⚠️ Ошибки"
BTN_LOGS = "📄 Логи"
BTN_HELP = "❓ Помощь"

# Permanent-admin only / Только главный админ
BTN_INVITE = "🎫 Инвайт"
BTN_BAN = "🚫 Бан"
BTN_UNBAN = "✅ Разбан"
BTN_REVOKE = "🔒 Отозвать"
BTN_BANNED = "📜 Баны"

# Navigation / Навигация
BTN_HIDE = "🙈 Скрыть меню"


def _kb(rows: list[list[str]], placeholder: str) -> ReplyKeyboardMarkup:
    """Build a resizable reply keyboard from a list of label rows"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=label) for label in row] for row in rows],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder=placeholder,
    )


def user_menu_keyboard() -> ReplyKeyboardMarkup:
    """Keyboard for regular (non-admin) users"""
    return _kb(
        [
            [BTN_CHANNELS, BTN_REPORT],
            [BTN_LOGIN],
        ],
        placeholder="Выберите действие или введите команду…",
    )


def admin_menu_keyboard(is_permanent: bool) -> ReplyKeyboardMarkup:
    """Keyboard for admins. Permanent admin gets the extra moderation row."""
    rows = [
        [BTN_PAIRS, BTN_STATUS],
        [BTN_CONNECT, BTN_AVATAR],
        [BTN_ENABLE, BTN_DISABLE, BTN_DELETE],
        [BTN_BACKFILL, BTN_BROADCAST],
        [BTN_ERRORS, BTN_LOGS, BTN_CHANNELS],
    ]

    if is_permanent:
        rows.append([BTN_INVITE, BTN_BAN, BTN_UNBAN])
        rows.append([BTN_REVOKE, BTN_BANNED])

    rows.append([BTN_HELP, BTN_HIDE])

    return _kb(rows, placeholder="Выберите действие или введите команду…")


def menu_keyboard_for_role(role: str) -> ReplyKeyboardMarkup:
    """Return the appropriate keyboard for a user role"""
    if role == "permanent_admin":
        return admin_menu_keyboard(is_permanent=True)
    if role == "temp_admin":
        return admin_menu_keyboard(is_permanent=False)
    return user_menu_keyboard()


def remove_keyboard() -> ReplyKeyboardRemove:
    """Hide the reply keyboard"""
    return ReplyKeyboardRemove()
