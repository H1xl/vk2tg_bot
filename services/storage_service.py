"""
Storage Service with Tortoise ORM and Write-Back Cache
Сервис хранилища с Tortoise ORM и write-back кэшем
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Optional

from tortoise.exceptions import DoesNotExist, IntegrityError
from tortoise.transactions import in_transaction

import config
from database.models import InviteCode, Pair, PairStats, User
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="storage_service")


class StorageService:
    """Service for database operations with write-back cache"""

    def __init__(self):
        self._last_post_cache = {}
        self._dirty_pairs = set()
        self._cache_lock = asyncio.Lock()
        self._cache_read_lock = asyncio.Lock()
        self._flush_task = None

    # =====
    # Cache management
    # Управление кэшем
    # =====

    async def start_cache_flushing(self):
        """Start background cache flushing task"""

        self._flush_task = asyncio.create_task(self._flush_cache_periodically())
        logger.info("cache_flush_started", interval=config.config.cache_flush_interval)

    async def stop_cache_flushing(self):
        """Stop cache flushing and perform final flush"""

        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass

        await self._flush_to_db()
        logger.info("cache_flush_stopped")

    async def _flush_cache_periodically(self):
        """Periodically flush cache to database"""

        while True:
            try:
                await asyncio.sleep(config.config.cache_flush_interval)
                await self._flush_to_db()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("cache_flush_error", error=str(e))

    async def _flush_to_db(self):
        """Atomic flush of dirty records to database"""

        async with self._cache_lock:
            if not self._dirty_pairs:
                return

            flush_count = len(self._dirty_pairs)

            for pair_id in list(self._dirty_pairs):
                try:
                    post_id = self._last_post_cache.get(pair_id)
                    if post_id is not None:
                        stats = await PairStats.filter(pair_id=pair_id).first()
                        if stats:
                            stats.last_post_id = post_id
                            stats.last_update = datetime.now()
                            await stats.save()
                            logger.debug("cache_flushed_pair", pair_id=pair_id, post_id=post_id)
                except Exception as e:
                    logger.error("cache_flush_pair_error", pair_id=pair_id, error=str(e))

            self._dirty_pairs.clear()
            logger.debug("cache_flushed", count=flush_count)

    async def clear_pair_cache(self, pair_id: str):
        """Clear cache for specific pair and reload from DB"""
        async with self._cache_lock:
            if pair_id in self._last_post_cache:
                del self._last_post_cache[pair_id]
            self._dirty_pairs.discard(pair_id)

        logger.debug("pair_cache_cleared", pair_id=pair_id)

    # =====
    # Pairs Management with optimized queries
    # Управление парами с оптимизированными запросами
    # =====

    async def get_all_pairs(self) -> List[Pair]:
        """Get all pairs"""
        return await Pair.all()

    async def get_pair_by_id(self, pair_id: str) -> Optional[Pair]:
        """Get pair by ID"""
        try:
            return await Pair.get(id=pair_id)
        except DoesNotExist:
            return None

    async def get_active_pairs(self) -> List[Pair]:
        """Get active pairs with prefetch for stats (N+1 optimization)"""
        return await Pair.filter(status="active").prefetch_related("stats").all()

    async def create_pair(
        self, pair_id: str, vk_id: int, tg_id: int, name: str = "", is_safe: bool = False
    ) -> Pair:
        """Create new pair with transaction"""
        try:
            async with in_transaction():
                pair = await Pair.create(
                    id=pair_id,
                    name=name,
                    vk_id=vk_id,
                    tg_id=tg_id,
                    is_safe=is_safe,
                    status="stopped",
                )

                await PairStats.create(pair=pair)

                logger.info("pair_created", pair_id=pair_id, vk_id=vk_id, tg_id=tg_id)
                return pair

        except IntegrityError:
            logger.error("pair_already_exists", pair_id=pair_id)
            raise ValueError(Messages.PAIR_EXISTS_ERROR.format(pair_id=pair_id))

    async def update_pair_status(self, pair_id: str, status: str) -> bool:
        """Update pair status"""
        updated = await Pair.filter(id=pair_id).update(status=status)

        if updated:
            logger.info("pair_status_updated", pair_id=pair_id, status=status)

        return updated > 0

    async def remove_pair(self, pair_id: str, vk_id: int = None) -> bool:
        """Remove pair with file cleanup (cascades to PairStats)"""
        deleted = await Pair.filter(id=pair_id).delete()

        if deleted:
            async with self._cache_lock:
                self._last_post_cache.pop(pair_id, None)
                self._dirty_pairs.discard(pair_id)

            if vk_id:
                try:
                    from services.media_handler import MediaHandler

                    media_handler = MediaHandler()
                    await media_handler.cleanup_pair_files(pair_id, vk_id)
                except Exception as e:
                    logger.warning("pair_files_cleanup_failed", pair_id=pair_id, error=str(e))

            logger.info("pair_deleted", pair_id=pair_id)

        return deleted > 0

    # =====
    # Last Post Management (with write-back cache)
    # Управление последними постами (с write-back кэшем)
    # =====

    async def get_last_post(self, pair_id: str) -> Optional[int]:
        """Get last_post_id (from cache first, then DB)"""
        async with self._cache_read_lock:
            if pair_id in self._last_post_cache:
                return self._last_post_cache[pair_id]

        try:
            stats = await PairStats.filter(pair_id=pair_id).first()
            if stats and stats.last_post_id is not None:
                post_id = stats.last_post_id

                # Only cache real values; never cache None permanently, otherwise a pair
                # that hasn't been initialized yet would be stuck returning None.
                # Кэшируем только реальные значения, чтобы не "застрять" на None.
                async with self._cache_lock:
                    self._last_post_cache[pair_id] = post_id

                return post_id
        except Exception as e:
            logger.error("get_last_post_error", pair_id=pair_id, error=str(e))

        return None

    async def set_last_post(self, pair_id: str, post_id: int):
        """Set last_post_id (update cache, DB write deferred)"""
        async with self._cache_lock:
            self._last_post_cache[pair_id] = post_id
            self._dirty_pairs.add(pair_id)

        logger.debug("last_post_updated_cache", pair_id=pair_id, post_id=post_id)

    # =====
    # Avatar Management
    # Управление аватарками
    # =====

    async def get_avatar_info(self, pair_id: str) -> Optional[dict]:
        """
        Get avatar hash and last update time
        Returns: dict with 'hash' and 'updated_at' or None
        """
        try:
            pair = await Pair.get(id=pair_id)

            avatar_hash = getattr(pair, "avatar_hash", None)
            avatar_updated_at = getattr(pair, "avatar_updated_at", None)

            return {"hash": avatar_hash, "updated_at": avatar_updated_at}
        except DoesNotExist:
            return None
        except Exception as e:
            logger.error("get_avatar_info_error", pair_id=pair_id, error=str(e))
            return None

    async def update_avatar_info(self, pair_id: str, avatar_hash: str):
        """Update avatar hash and timestamp"""
        try:
            pair = await Pair.get(id=pair_id)

            if hasattr(pair, "avatar_hash"):
                pair.avatar_hash = avatar_hash
                pair.avatar_updated_at = datetime.now()
                await pair.save()

                logger.info("avatar_info_updated", pair_id=pair_id, hash=avatar_hash[:8])
                return True
            else:
                logger.error(
                    "avatar_fields_missing",
                    pair_id=pair_id,
                    message="Run migrate_db.py to add avatar fields",
                )
                return False

        except DoesNotExist:
            logger.error("avatar_update_pair_not_found", pair_id=pair_id)
            return False
        except Exception as e:
            logger.error("avatar_update_error", pair_id=pair_id, error=str(e))
            return False

    async def get_pairs_for_avatar_update(self, interval_hours: int = 24) -> List[Pair]:
        """
        Get pairs that need avatar update
        Returns pairs where avatar_updated_at is older than interval_hours or None
        """
        cutoff_time = datetime.now() - timedelta(hours=interval_hours)

        try:
            pairs = (
                await Pair.filter(status="active").filter(avatar_updated_at__lt=cutoff_time).all()
            )

            pairs_without_avatar = await Pair.filter(
                status="active", avatar_updated_at__isnull=True
            ).all()

            all_pairs = pairs + pairs_without_avatar

            logger.debug("pairs_for_avatar_update", count=len(all_pairs))
            return all_pairs

        except Exception as e:
            logger.error("get_pairs_for_avatar_update_error", error=str(e))
            return []

    # =====
    # Posts 24h Statistics
    # Статистика постов за 24ч
    # =====

    async def increment_posts_24h(self, pair_id: str):
        """Increment 24h post counter"""
        try:
            stats = await PairStats.filter(pair_id=pair_id).first()
            if stats:
                stats.posts_24h += 1
                await stats.save()
        except Exception as e:
            logger.error("increment_posts_24h_error", pair_id=pair_id, error=str(e))

    async def reset_old_posts_24h(self):
        """Reset counters older than 24h"""
        cutoff = datetime.now() - timedelta(hours=24)

        await PairStats.filter(last_update__lt=cutoff).update(posts_24h=0)

        logger.debug("posts_24h_reset", cutoff=cutoff.isoformat())

    async def get_posts_24h(self, pair_id: str) -> int:
        """Get 24h post count"""
        try:
            stats = await PairStats.filter(pair_id=pair_id).first()
            return stats.posts_24h if stats else 0
        except Exception as e:
            logger.error("get_posts_24h_error", pair_id=pair_id, error=str(e))
            return 0
