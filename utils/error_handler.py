"""
Error Handler for centralized error handling
Обработчик ошибок для централизованной обработки ошибок
"""

from functools import wraps
from typing import Optional

from aiogram.types import Message

from utils.helpers import escape_html
from utils.logger import logger
from utils.messages import Messages

# =====
# Decorator for handler error handling
# Декоратор для обработки ошибок в обработчиках
# =====


def handle_errors(
    error_message: Optional[str] = None, log_error: bool = True, notify_user: bool = True
):
    """
    Decorator for handling errors in message handlers

    Args:
        error_message: Custom error message to show user
        log_error: Whether to log the error
        notify_user: Whether to notify user about error
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(message: Message, *args, **kwargs):
            try:
                return await func(message, *args, **kwargs)
            except Exception as e:
                if log_error:
                    user = getattr(message, "from_user", None)
                    logger.error(
                        f"{func.__name__}_error",
                        user_id=user.id if user else None,
                        error=str(e),
                        exc_info=True,
                    )

                if notify_user:
                    msg = error_message or Messages.GENERIC_ERROR
                    try:
                        await message.answer(msg, parse_mode="HTML")
                    except Exception as send_error:
                        logger.error("error_message_send_failed", error=str(send_error))

        return wrapper

    return decorator


# =====
# Context manager for error handling
# Контекстный менеджер для обработки ошибок
# =====


class ErrorContext:
    """Context manager for handling errors in code blocks"""

    def __init__(
        self,
        operation: str,
        message: Optional[Message] = None,
        notify_user: bool = False,
        user_message: Optional[str] = None,
    ):
        self.operation = operation
        self.message = message
        self.notify_user = notify_user
        self.user_message = user_message

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            logger.error(
                f"{self.operation}_error", error=str(exc_val), exc_info=(exc_type, exc_val, exc_tb)
            )

            if self.notify_user and self.message:
                msg = self.user_message or Messages.GENERIC_ERROR
                try:
                    await self.message.answer(msg, parse_mode="HTML")
                except Exception as e:
                    logger.error("error_notification_failed", error=str(e))

            return True
        return False
