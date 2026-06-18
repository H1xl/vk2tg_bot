"""
Queue Manager for API rate limiting
Менеджер очередей для ограничения частоты запросов к API
"""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Any, Callable, Dict

import config

# =====
# Basic Queue Manager
# Базовый менеджер очередей
# =====


class QueueManager:
    """Async queue manager for API rate limiting"""

    def __init__(self, requests_per_second: float = 3.0):
        self.requests_per_second = requests_per_second
        self.min_interval = 1.0 / requests_per_second
        self.last_request_time = None
        self._lock = asyncio.Lock()

    async def execute(self, func: Callable, *args, **kwargs) -> Any:
        """Execute function with rate limiting"""
        async with self._lock:
            # Calculate time to wait / Вычислить время ожидания
            if self.last_request_time:
                elapsed = (datetime.now() - self.last_request_time).total_seconds()
                wait_time = max(0, self.min_interval - elapsed)

                if wait_time > 0:
                    await asyncio.sleep(wait_time)

            # Execute function / Выполнить функцию
            self.last_request_time = datetime.now()
            return await func(*args, **kwargs)


# =====
# Per-Channel Queue Manager
# Менеджер очередей для каждого канала
# =====


class ChannelQueueManager:
    """Per-channel queue manager for Telegram API"""

    def __init__(self, messages_per_minute: int = 20):
        self.messages_per_minute = messages_per_minute
        self.channel_queues: Dict[int, deque] = {}
        self._locks: Dict[int, asyncio.Lock] = {}

    def _get_lock(self, channel_id: int) -> asyncio.Lock:
        """Get or create lock for channel"""
        if channel_id not in self._locks:
            self._locks[channel_id] = asyncio.Lock()
        return self._locks[channel_id]

    def _get_queue(self, channel_id: int) -> deque:
        """Get or create queue for channel"""
        if channel_id not in self.channel_queues:
            self.channel_queues[channel_id] = deque()
        return self.channel_queues[channel_id]

    async def execute(self, channel_id: int, func: Callable, *args, **kwargs) -> Any:
        """Execute function with per-channel rate limiting"""
        lock = self._get_lock(channel_id)
        queue = self._get_queue(channel_id)

        async with lock:
            current_time = datetime.now()
            cutoff_time = current_time - timedelta(minutes=1)

            # Remove old timestamps / Удалить старые временные метки
            while queue and queue[0] < cutoff_time:
                queue.popleft()

            # Check if at limit / Проверить достигнут ли лимит
            if len(queue) >= self.messages_per_minute:
                # Calculate wait time / Вычислить время ожидания
                oldest_timestamp = queue[0]
                wait_seconds = 60 - (current_time - oldest_timestamp).total_seconds()

                if wait_seconds > 0:
                    from utils.logger import logger

                    logger.info(
                        "channel_rate_limit", channel_id=channel_id, wait_seconds=wait_seconds
                    )
                    await asyncio.sleep(wait_seconds)

                    # Cleanup again after waiting / Очистить снова после ожидания
                    current_time = datetime.now()
                    cutoff_time = current_time - timedelta(minutes=1)
                    while queue and queue[0] < cutoff_time:
                        queue.popleft()

            # Execute function / Выполнить функцию
            result = await func(*args, **kwargs)

            # Record timestamp / Записать временную метку
            queue.append(current_time)

            return result


# =====
# Global queue instances
# Глобальные экземпляры очередей
# =====

vk_queue = QueueManager(requests_per_second=config.config.vk_requests_per_second)
telegram_queue = QueueManager(requests_per_second=config.config.tg_requests_per_second)
telegram_channel_queue = ChannelQueueManager(
    messages_per_minute=config.config.tg_messages_per_minute_per_chat
)
