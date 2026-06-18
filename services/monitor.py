"""
Monitor Service with graceful degradation
Сервис мониторинга с graceful degradation
"""

import asyncio
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import config
from utils.helpers import calculate_image_hash, cleanup_temp_files
from utils.link_formatter import format_vk_post_link
from utils.logger import log_error, logger
from utils.messages import Messages
from utils.retry_helper import MONITOR_STRATEGY, retry_post_forward

from .media_handler import MediaHandler
from .post_forwarder import PostForwarder
from .storage_service import StorageService
from .telegram_service import TelegramService
from .vk_service import VKService

logger = logger.bind(module="monitor")


class Monitor:
    """Monitoring service for VK to Telegram forwarding"""

    def __init__(
        self,
        bot,
        vk_service: VKService = None,
        telegram_service: TelegramService = None,
        storage_service: StorageService = None,
        media_handler: MediaHandler = None,
        post_forwarder: PostForwarder = None,
    ):
        self.bot = bot
        # Use shared service instances (dependency injection). Falling back to new
        # instances only when used stand-alone (e.g. tests).
        # Используем общие экземпляры сервисов (DI); создаём новые только при автономном запуске.
        self.vk_service = vk_service or VKService()
        self.telegram_service = telegram_service or TelegramService(bot)
        self.storage_service = storage_service or StorageService()
        self.media_handler = media_handler or MediaHandler()
        self.post_forwarder = post_forwarder or PostForwarder(
            self.vk_service, self.telegram_service, self.media_handler
        )

        self.is_running = False
        self.is_processing = False
        self.shutdown_event = asyncio.Event()
        self.last_cycle_time = None
        self.last_cleanup_time = datetime.now()
        self.total_posts_forwarded = 0
        self.forwarding_times = []

        self.checked_posts_cache: Dict[int, bool] = {}
        self.CHECKED_POSTS_CACHE_SIZE = config.config.checked_posts_cache_size
        self._cache_timestamps: Dict[int, datetime] = {}

        # Deferred ad-check queue for unsafe pairs: pair_id -> {post_id: {post, detected_at}}.
        # A newly seen post waits ad_check_delay_minutes before its comments are checked,
        # so ads posted right after publication appear before the check runs.
        # Отложенная проверка рекламы для небезопасных пар: пост ждёт N минут до проверки комментариев.
        self._pending_ad_checks: Dict[str, Dict[int, Dict]] = {}

        self._monitor_cycle_count = 0

    # =====
    # Main monitoring loop
    # Основной цикл мониторинга
    # =====

    async def start(self):
        """Start monitoring loop"""
        self.is_running = True

        logger.info("monitor_started")

        while self.is_running:
            try:
                cycle_start = datetime.now()
                self.is_processing = True

                if self.shutdown_event.is_set():
                    logger.info("monitor_shutdown_signal")
                    self.is_processing = False
                    break

                active_pairs = await self.storage_service.get_active_pairs()

                if active_pairs:
                    await self._process_pairs(active_pairs)

                self._monitor_cycle_count += 1

                if self._monitor_cycle_count >= config.config.avatar_check_on_monitor_cycles:
                    self._monitor_cycle_count = 0
                    await self._check_and_update_avatars()

                if (datetime.now() - self.last_cleanup_time).total_seconds() > 600:
                    await cleanup_temp_files(max_age_seconds=7200)
                    self.last_cleanup_time = datetime.now()

                self.last_cycle_time = datetime.now()
                self.is_processing = False

                elapsed = (datetime.now() - cycle_start).total_seconds()
                sleep_time = max(0, config.config.monitor_interval - elapsed)

                logger.debug(
                    "monitor_cycle_complete", elapsed=f"{elapsed:.2f}s", sleep=f"{sleep_time:.2f}s"
                )

                try:
                    await asyncio.wait_for(self.shutdown_event.wait(), timeout=sleep_time)
                    break
                except asyncio.TimeoutError:
                    pass

            except Exception as e:
                await log_error(f"Monitor cycle error: {e}", is_critical=True)
                self.is_processing = False
                await asyncio.sleep(60)

        logger.info("monitor_stopped")

    def stop(self):
        """Stop monitoring loop gracefully"""
        self.is_running = False
        self.shutdown_event.set()
        logger.info("monitor_stop_requested")

    async def wait_for_completion(self):
        """Wait for current processing to complete"""
        max_wait = 60
        wait_start = datetime.now()

        while self.is_processing:
            if (datetime.now() - wait_start).total_seconds() > max_wait:
                logger.warning("monitor_shutdown_timeout")
                break
            await asyncio.sleep(0.5)

    # =====
    # Process pairs
    # Обработка пар
    # =====

    async def _process_pairs(self, pairs: List):
        """Process all active pairs"""
        for pair in pairs:
            if self.shutdown_event.is_set():
                break

            try:
                await self._process_single_pair(pair)
            except Exception as e:
                pair_id = pair.id
                logger.error("pair_processing_error", pair_id=pair_id, error=str(e))

    async def _process_single_pair(self, pair):
        """Process single pair with strict mode"""
        pair_id = pair.id
        vk_id = pair.vk_id
        tg_id = pair.tg_id
        is_safe = pair.is_safe

        if pair.status != "active":
            logger.debug("pair_not_active_skipping", pair_id=pair_id, status=pair.status)
            return

        last_post_id = await self.storage_service.get_last_post(pair_id)

        logger.debug("monitor_checking_pair", pair_id=pair_id, last_post_id=last_post_id)

        new_posts = await self.vk_service.get_new_posts(vk_id, last_post_id)

        # Unsafe pairs: defer each new post by ad_check_delay_minutes, then check
        # comments for links before forwarding (see _process_unsafe_pair). Always run,
        # even with no new posts, so previously-queued posts whose timer elapsed get sent.
        # Небезопасные пары: откладываем каждый новый пост и проверяем комментарии позже.
        if not is_safe:
            await self._process_unsafe_pair(pair, new_posts or [])
            return

        if not new_posts:
            return

        logger.info("processing_new_posts", pair_id=pair_id, count=len(new_posts))

        for post in new_posts:
            pair = await self.storage_service.get_pair_by_id(pair_id)
            if not pair or pair.status != "active":
                logger.info("pair_stopped_during_processing", pair_id=pair_id)
                break

            if self.shutdown_event.is_set():
                break

            post_id = post.get("id")

            forward_start = datetime.now()
            success = await self._forward_post_with_guaranteed_delivery(pair, post)

            if success:
                await self.storage_service.set_last_post(pair_id, post_id)
                self.total_posts_forwarded += 1

                # Track forwarding time (bounded to last 100 to avoid unbounded growth)
                # Учитываем время пересылки (не более 100 последних, чтобы не рос список)
                elapsed = (datetime.now() - forward_start).total_seconds()
                self.forwarding_times.append(elapsed)
                if len(self.forwarding_times) > 100:
                    del self.forwarding_times[0]
            else:
                logger.error("pair_stopped_at_post", pair_id=pair_id, post_id=post_id)
                break

    async def _process_unsafe_pair(self, pair, new_posts: List):
        """
        Deferred ad-check pipeline for unsafe pairs.

        Each newly seen post is queued with a detection timestamp WITHOUT advancing
        last_post_id. Once a post has waited `ad_check_delay_minutes`, its first
        comments are checked for links; if an ad link is found the post is skipped,
        otherwise it is forwarded. Only then is last_post_id advanced.

        Not advancing last_post_id until a post is resolved means queued posts survive
        a restart (they are re-discovered from VK) and ordering is preserved by
        processing in ascending post id and stopping at the first not-yet-due post.
        """
        pair_id = pair.id
        vk_id = pair.vk_id

        pending = self._pending_ad_checks.setdefault(pair_id, {})

        # Register newly seen posts (dedupe by id; keep the original detection time).
        for post in new_posts:
            pid = post.get("id")
            if pid is None or pid in pending:
                continue
            pending[pid] = {"post": post, "detected_at": datetime.now()}
            logger.info(
                "post_queued_for_ad_check",
                pair_id=pair_id,
                post_id=pid,
                delay_min=config.config.ad_check_delay_minutes,
            )

        if not pending:
            return

        delay = timedelta(minutes=config.config.ad_check_delay_minutes)
        now = datetime.now()

        # Ascending id == chronological. Stop at the first post still within its delay
        # window (newer posts are even less due), preserving order and the high-water mark.
        for pid in sorted(pending.keys()):
            if self.shutdown_event.is_set():
                break

            fresh = await self.storage_service.get_pair_by_id(pair_id)
            if not fresh or fresh.status != "active":
                logger.info("pair_stopped_during_processing", pair_id=pair_id)
                break

            entry = pending[pid]
            if now - entry["detected_at"] < delay:
                break

            post = entry["post"]

            is_safe_post = await self.check_post_for_ads(vk_id, pid)
            if not is_safe_post:
                logger.info(
                    "post_skipped_ad",
                    pair_id=pair_id,
                    post_id=pid,
                    vk_url=format_vk_post_link(vk_id, pid),
                )
                await self.storage_service.set_last_post(pair_id, pid)
                del pending[pid]
                continue

            forward_start = datetime.now()
            success = await self._forward_post_with_guaranteed_delivery(fresh, post)

            if success:
                await self.storage_service.set_last_post(pair_id, pid)
                self.total_posts_forwarded += 1
                elapsed = (datetime.now() - forward_start).total_seconds()
                self.forwarding_times.append(elapsed)
                if len(self.forwarding_times) > 100:
                    del self.forwarding_times[0]
                del pending[pid]
            else:
                logger.error("pair_stopped_at_post", pair_id=pair_id, post_id=pid)
                break

        if not pending:
            self._pending_ad_checks.pop(pair_id, None)

    # =====
    # Forward post with guaranteed delivery (STRICT MODE)
    # Пересылка поста с гарантированной доставкой (СТРОГИЙ РЕЖИМ)
    # =====

    async def _forward_post_with_guaranteed_delivery(self, pair, post: Dict) -> bool:
        """Forward post with retries until success or stop pair"""
        pair_id = pair.id
        pair_name = pair.name or pair_id
        vk_id = pair.vk_id
        post_id = post.get("id")

        async def forward_func():
            return await self.post_forwarder.forward_post(post, pair.tg_id)

        success, _ = await retry_post_forward(
            forward_func, MONITOR_STRATEGY, log_prefix=f"monitor_post_{pair_id}"
        )

        if success:
            logger.info("post_forwarded", pair_id=pair_id, post_id=post_id)
            return True

        error_message = Messages.MONITOR_FORWARD_FAILED.format(
            attempts=MONITOR_STRATEGY.max_attempts
        )

        await log_error(
            f"CRITICAL: Failed to forward post {post_id} for pair {pair_id} after {MONITOR_STRATEGY.max_attempts} attempts. Stopping pair.",
            is_critical=True,
        )

        await self.storage_service.update_pair_status(pair_id, "stopped")

        await self.media_handler.cleanup_pair_files(pair_id, vk_id)

        try:
            notification_text = Messages.MONITOR_PAIR_STOPPED_NOTIFICATION.format(
                pair_id=pair_id,
                pair_name=pair_name,
                vk_id=vk_id,
                post_id=post_id,
                error_message=error_message,
                attempts=MONITOR_STRATEGY.max_attempts,
            )

            await self.bot.send_message(
                config.config.error_channel_id, notification_text, parse_mode="HTML"
            )
        except Exception as e:
            logger.error("error_notification_failed", error=str(e))

        logger.info("pair_stopped_due_to_failure", pair_id=pair_id)

        return False

    # =====
    # Ad check for unsafe pairs (public method for shared use)
    # Проверка рекламы для unsafe пар (публичный метод для общего использования)
    # =====

    async def check_post_for_ads(self, vk_id: int, post_id: int) -> bool:
        """Check if post contains ads in first N comments (public, shared with /backfill)"""
        await self._cleanup_expired_cache()

        if post_id in self.checked_posts_cache and post_id in self._cache_timestamps:
            age = datetime.now() - self._cache_timestamps[post_id]
            if age < timedelta(hours=config.config.checked_posts_cache_ttl_hours):
                return self.checked_posts_cache[post_id]
            else:
                del self.checked_posts_cache[post_id]
                del self._cache_timestamps[post_id]

        try:
            comments = await self.vk_service.get_post_comments(
                vk_id, post_id, count=config.config.comments_to_check
            )

            url_pattern = r"https?://[^\s]+"

            for comment in comments:
                text = comment.get("text", "")
                if re.search(url_pattern, text):
                    logger.info("post_ad_detected", post_id=post_id)

                    self._add_to_cache(post_id, False)
                    return False

            self._add_to_cache(post_id, True)
            return True

        except Exception as e:
            logger.error("ad_check_error", post_id=post_id, error=str(e))
            self._add_to_cache(post_id, True)
            return True

    async def _cleanup_expired_cache(self):
        """Remove expired entries from cache"""
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(hours=config.config.checked_posts_cache_ttl_hours)

        expired_keys = [k for k, v in self._cache_timestamps.items() if v < cutoff_time]

        for k in expired_keys:
            if k in self.checked_posts_cache:
                del self.checked_posts_cache[k]
            if k in self._cache_timestamps:
                del self._cache_timestamps[k]

        if expired_keys:
            logger.debug("cache_expired_removed", count=len(expired_keys))

    def _add_to_cache(self, post_id: int, is_safe: bool):
        """Add post to checked cache with TTL and size limit"""
        current_time = datetime.now()

        if len(self.checked_posts_cache) >= self.CHECKED_POSTS_CACHE_SIZE:
            if self._cache_timestamps:
                oldest_post_id = min(
                    self._cache_timestamps.keys(), key=lambda k: self._cache_timestamps[k]
                )
                if oldest_post_id in self.checked_posts_cache:
                    del self.checked_posts_cache[oldest_post_id]
                if oldest_post_id in self._cache_timestamps:
                    del self._cache_timestamps[oldest_post_id]

        self.checked_posts_cache[post_id] = is_safe
        self._cache_timestamps[post_id] = current_time

    # =====
    # Avatar update checking
    # Проверка обновления аватарок
    # =====

    async def _check_and_update_avatars(self):
        """Check and update avatars for pairs that need it"""
        try:
            pairs = await self.storage_service.get_pairs_for_avatar_update(
                interval_hours=config.config.avatar_update_interval_hours
            )

            if not pairs:
                logger.debug("no_pairs_need_avatar_update")
                return

            logger.info("checking_avatars", count=len(pairs))

            for pair in pairs:
                if self.shutdown_event.is_set():
                    break

                try:
                    await self._update_pair_avatar(pair, notify=False)
                    await asyncio.sleep(2)
                except Exception as e:
                    logger.error("avatar_auto_update_failed", pair_id=pair.id, error=str(e))

        except Exception as e:
            logger.error("avatar_check_error", error=str(e))

    async def _update_pair_avatar(self, pair, notify: bool = False) -> bool:
        """
        Update avatar for a single pair
        Returns: True if updated, False if no change or error
        """
        pair_id = pair.id
        vk_id = pair.vk_id
        tg_id = pair.tg_id

        try:
            avatar_url = await self.vk_service.get_group_photo(vk_id, size="photo_200")

            if not avatar_url:
                logger.warning("avatar_vk_not_found", pair_id=pair_id)
                return False

            avatar_path = await self.media_handler.download_photo(avatar_url, f"avatar_{vk_id}.jpg")

            if not avatar_path:
                logger.warning("avatar_download_failed", pair_id=pair_id)
                return False

            try:
                new_hash = await calculate_image_hash(avatar_path)

                if not new_hash:
                    logger.warning("avatar_hash_failed", pair_id=pair_id)
                    return False

                avatar_info = await self.storage_service.get_avatar_info(pair_id)
                old_hash = avatar_info.get("hash") if avatar_info else None

                if old_hash and old_hash == new_hash:
                    logger.debug("avatar_no_change", pair_id=pair_id)
                    await self.storage_service.update_avatar_info(pair_id, new_hash)
                    return False

                success = await self.telegram_service.update_channel_avatar(tg_id, avatar_path)

                if success:
                    await self.storage_service.update_avatar_info(pair_id, new_hash)

                    logger.info("avatar_updated", pair_id=pair_id)

                    return True
                else:
                    logger.error("avatar_tg_update_failed", pair_id=pair_id)
                    return False

            finally:
                await self.media_handler.cleanup_file(avatar_path)

        except Exception as e:
            logger.error("avatar_update_error", pair_id=pair_id, error=str(e))
            return False

    # =====
    # Statistics
    # Статистика
    # =====

    def get_average_forwarding_time(self) -> float:
        """Get average post forwarding time"""
        if not self.forwarding_times:
            return 0.0
        return sum(self.forwarding_times) / len(self.forwarding_times)
