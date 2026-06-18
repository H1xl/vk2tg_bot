"""
Retry Helper for unified retry logic
Вспомогательный модуль для унифицированной логики повторов
"""

import asyncio
from typing import Any, Callable, Optional, Tuple

from aiogram.exceptions import TelegramRetryAfter

import config
from utils.logger import logger

# =====
# Retry strategies
# Стратегии повторов
# =====


class RetryStrategy:
    """Base retry strategy configuration"""

    def __init__(
        self, max_attempts: int = None, delays: list[int] = None, use_flood_wait: bool = True
    ):
        self.max_attempts = max_attempts or config.config.max_retry_attempts
        self.delays = delays or config.config.retry_delays
        self.use_flood_wait = use_flood_wait

    def get_delay(self, attempt: int, flood_wait: Optional[int] = None) -> int:
        """
        Calculate delay for retry attempt
        Returns delay in seconds
        """
        if self.use_flood_wait and flood_wait:
            return flood_wait + 5

        if attempt < len(self.delays):
            return self.delays[attempt]

        return self.delays[-1] if self.delays else 60


# Predefined strategies / Предопределенные стратегии
MONITOR_STRATEGY = RetryStrategy(
    max_attempts=5, delays=[30, 60, 120, 240, 480], use_flood_wait=True
)

FILL_STRATEGY = RetryStrategy(max_attempts=3, delays=[5, 10, 15], use_flood_wait=True)

TELEGRAM_API_STRATEGY = RetryStrategy(max_attempts=3, delays=[2, 5, 10], use_flood_wait=True)

# =====
# Retry decorator for post forwarding
# Декоратор повтора для пересылки постов
# =====


async def retry_post_forward(
    forward_func: Callable, strategy: RetryStrategy, log_prefix: str = "post_forward"
) -> Tuple[bool, Optional[int]]:
    """
    Retry post forwarding with strategy
    Returns: (success, retry_after_seconds)
    """
    for attempt in range(strategy.max_attempts):
        try:
            success, is_flood_wait, retry_after = await forward_func()

            if success:
                return (True, None)

            # Calculate wait time / Расчёт времени ожидания
            if attempt < strategy.max_attempts - 1:
                wait_time = strategy.get_delay(attempt, retry_after if is_flood_wait else None)

                if is_flood_wait and retry_after:
                    logger.warning(
                        f"{log_prefix}_flood_wait", wait_seconds=wait_time, attempt=attempt + 1
                    )
                else:
                    logger.warning(
                        f"{log_prefix}_retry", wait_seconds=wait_time, attempt=attempt + 1
                    )

                await asyncio.sleep(wait_time)

        except Exception as e:
            logger.error(f"{log_prefix}_error", attempt=attempt + 1, error=str(e))

            if attempt < strategy.max_attempts - 1:
                wait_time = strategy.get_delay(attempt)
                await asyncio.sleep(wait_time)
            else:
                raise

    return (False, None)


# =====
# Retry decorator for Telegram API calls
# Декоратор повтора для Telegram API вызовов
# =====


async def retry_telegram_api(
    api_func: Callable, strategy: RetryStrategy = TELEGRAM_API_STRATEGY
) -> Tuple[Optional[Any], Optional[int]]:
    """
    Retry Telegram API call with flood wait handling
    Returns: (result, retry_after_seconds)
    """
    for attempt in range(strategy.max_attempts):
        try:
            result = await api_func()
            return (result, None)

        except TelegramRetryAfter as e:
            retry_after = e.retry_after

            if attempt < strategy.max_attempts - 1:
                wait_time = retry_after + 5
                logger.warning(
                    "telegram_api_flood_wait", retry_after=retry_after, attempt=attempt + 1
                )
                await asyncio.sleep(wait_time)
            else:
                return (None, retry_after)

        except Exception as e:
            logger.error("telegram_api_error", error=str(e), attempt=attempt + 1)

            if attempt == strategy.max_attempts - 1:
                raise

    return (None, None)


# =====
# Generic retry with exponential backoff
# Универсальный retry с экспоненциальной задержкой
# =====


async def retry_with_backoff(
    func: Callable,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    exponential: bool = True,
    log_prefix: str = "operation",
) -> Any:
    """
    Retry function with exponential or linear backoff
    Raises last exception if all attempts fail
    """
    last_exception = None

    for attempt in range(max_attempts):
        try:
            return await func()

        except Exception as e:
            last_exception = e

            if attempt < max_attempts - 1:
                if exponential:
                    delay = base_delay * (2**attempt)
                else:
                    delay = base_delay

                logger.warning(
                    f"{log_prefix}_retry", attempt=attempt + 1, delay=delay, error=str(e)
                )

                await asyncio.sleep(delay)

    if last_exception:
        raise last_exception
