"""
System handlers with HTML formatting
Системные обработчики с HTML форматированием
"""

import os
from datetime import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import FSInputFile, Message

import config
from handlers.auth import require_auth
from utils.helpers import escape_html
from utils.logger import get_errors_last_24h, get_last_errors, logger
from utils.messages import Messages

logger = logger.bind(module="system_handlers")

router = Router()
storage_service = None
_monitor = None

# =====
# /start command
# Команда /start
# =====


async def cmd_start(message: Message):
    """Handle /start command"""
    await message.answer(Messages.START_MESSAGE, parse_mode="HTML")
    logger.info("start_command", user_id=message.from_user.id)


# =====
# /help command (admin only)
# Команда /help (только для админов)
# =====


@require_auth
async def cmd_help(message: Message):
    """Handle /help command"""
    await message.answer(Messages.HELP_MESSAGE, parse_mode="HTML")
    logger.info("help_command", user_id=message.from_user.id)


# =====
# /status command
# Команда /status
# =====


@require_auth
async def cmd_status(message: Message):
    """Handle /status command"""
    monitor = _monitor
    # Get statistics / Получить статистику
    all_pairs = await storage_service.get_all_pairs()
    active_pairs = await storage_service.get_active_pairs()

    # Last cycle time / Время последнего цикла
    last_cycle = monitor.last_cycle_time
    last_cycle_str = last_cycle.strftime("%Y-%m-%d %H:%M:%S") if last_cycle else "N/A"

    # Errors count / Количество ошибок
    errors_count = get_errors_last_24h()

    # Average forwarding time / Среднее время пересылки
    avg_time = monitor.get_average_forwarding_time()

    # Total posts forwarded / Всего постов переслано
    total_posts = monitor.total_posts_forwarded

    status_text = Messages.STATUS_MESSAGE.format(
        total_pairs=len(all_pairs),
        active_pairs=len(active_pairs),
        last_cycle=last_cycle_str,
        errors_24h=errors_count,
        avg_time=avg_time,
        total_posts=total_posts,
    )

    await message.answer(status_text, parse_mode="HTML")
    logger.info("status_command", user_id=message.from_user.id)


# =====
# /errors command
# Команда /errors
# =====


@require_auth
async def cmd_errors(message: Message):
    """Handle /errors command"""
    # Get error statistics / Получить статистику ошибок
    errors_24h = get_errors_last_24h()
    last_errors = get_last_errors(5)

    if not last_errors:
        await message.answer(Messages.ERRORS_NONE, parse_mode="HTML")
        return

    # Format errors as an expandable quote (collapses long lists, keeps chat tidy)
    # Ошибки в сворачиваемой цитате (длинный список не растягивает чат)
    header = Messages.ERRORS_HEADER.format(count=errors_24h, shown=len(last_errors))

    lines = []
    for i, error in enumerate(last_errors, 1):
        line = str(error).replace("\n", " ")
        if len(line) > 200:
            line = line[:199] + "…"
        lines.append(f"<b>{i}.</b> " + escape_html(line))

    errors_text = header + "\n<blockquote expandable>" + "\n".join(lines) + "</blockquote>"

    await message.answer(errors_text, parse_mode="HTML")
    logger.info("errors_command", user_id=message.from_user.id)


# =====
# /logs command
# Команда /logs
# =====


@require_auth
async def cmd_logs(message: Message):
    """Handle /logs command"""
    log_file = config.config.log_file

    if not os.path.exists(log_file):
        await message.answer(Messages.LOGS_NOT_FOUND, parse_mode="HTML")
        return

    try:
        log_document = FSInputFile(log_file)
        await message.answer_document(log_document, caption=Messages.LOGS_CAPTION)
        logger.info("logs_command", user_id=message.from_user.id)

    except Exception as e:
        logger.error("logs_send_failed", user_id=message.from_user.id, error=str(e))
        await message.answer(Messages.LOGS_SEND_FAILED, parse_mode="HTML")


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_system_handlers(dp, monitor, storage_svc):
    """Setup system command handlers with shared service instances"""
    global storage_service, _monitor
    storage_service = storage_svc
    _monitor = monitor

    # Public commands / Публичные команды
    router.message.register(cmd_start, Command("start"))

    # Protected commands / Защищённые команды
    router.message.register(cmd_help, Command("help", "h"))
    router.message.register(cmd_status, Command("status", "st"))
    router.message.register(cmd_errors, Command("errors", "err"))
    router.message.register(cmd_logs, Command("logs", "log"))

    dp.include_router(router)
