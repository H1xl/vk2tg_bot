"""
Link Formatter for centralized link formatting with caching
Форматировщик ссылок с централизованным форматированием и кэшированием
"""

from collections import OrderedDict
from typing import Optional

from utils.helpers import escape_html

# Max number of cached user links (bounded LRU to avoid unbounded growth)
# Максимум кэшируемых ссылок на пользователей (ограниченный LRU)
_USER_CACHE_MAXSIZE = 1000

# =====
# Link formatter with cache
# Форматировщик ссылок с кэшем
# =====


class LinkFormatter:
    """Centralized link formatter with a bounded user-link cache"""

    def __init__(self):
        # Bounded LRU cache for user links / Ограниченный LRU-кэш ссылок пользователей
        self._user_link_cache: "OrderedDict[int, str]" = OrderedDict()

    def format_user_link(
        self,
        user_id: int,
        username: Optional[str] = None,
        full_name: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """
        Format user link for Telegram HTML
        Returns clickable link to user profile
        """
        # Check cache / Проверка кэша
        if use_cache and user_id in self._user_link_cache:
            self._user_link_cache.move_to_end(user_id)
            return self._user_link_cache[user_id]

        # Format link / Форматирование ссылки
        if username:
            link = f'<a href="tg://user?id={user_id}">@{escape_html(username)}</a>'
        elif full_name:
            link = f'<a href="tg://user?id={user_id}">{escape_html(full_name)}</a>'
        else:
            link = f'<a href="tg://user?id={user_id}">ID: {user_id}</a>'

        # Cache result with LRU eviction / Кэшируем с вытеснением по LRU
        if use_cache:
            self._user_link_cache[user_id] = link
            self._user_link_cache.move_to_end(user_id)
            if len(self._user_link_cache) > _USER_CACHE_MAXSIZE:
                self._user_link_cache.popitem(last=False)

        return link

    def format_channel_link(
        self,
        channel_id: int,
        channel_title: Optional[str] = None,
        channel_username: Optional[str] = None,
        use_cache: bool = True,
    ) -> str:
        """
        Format channel link for Telegram HTML
        Returns clickable link if username available, otherwise title with ID.
        NOT cached: a channel's title/username can change, so cached values would go stale.
        Не кэшируется: title/username канала меняются, кэш отдавал бы устаревшее.
        """
        if channel_username:
            return f'<a href="https://t.me/{channel_username}">{escape_html(channel_title or channel_username)}</a>'
        elif channel_title:
            return f"<b>{escape_html(channel_title)}</b> (<code>{channel_id}</code>)"
        else:
            return f"<code>{channel_id}</code>"

    def format_vk_post_link(self, owner_id: int, post_id: int) -> str:
        """
        Format VK post link
        Returns: https://vk.com/wall-{owner_id}_{post_id}
        """
        return f"https://vk.com/wall-{owner_id}_{post_id}"

    def format_vk_group_link(self, group_id: int, screen_name: Optional[str] = None) -> str:
        """
        Format VK group link
        Returns: https://vk.com/{screen_name} or https://vk.com/club{group_id}
        """
        if screen_name:
            return f"https://vk.com/{screen_name}"
        return f"https://vk.com/club{group_id}"

    def clear_cache(self):
        """Clear all caches"""
        self._user_link_cache.clear()

    def clear_user_cache(self, user_id: Optional[int] = None):
        """Clear user link cache for specific user or all users"""
        if user_id is not None:
            self._user_link_cache.pop(user_id, None)
        else:
            self._user_link_cache.clear()

    def clear_channel_cache(self, channel_id: Optional[int] = None):
        """No-op: channel links are no longer cached (kept for backward compatibility)"""
        return None


# =====
# Global formatter instance
# Глобальный экземпляр форматировщика
# =====

link_formatter = LinkFormatter()

# =====
# Convenience functions for backward compatibility
# Функции для обратной совместимости
# =====


def format_user_link(
    user_id: int, username: Optional[str] = None, full_name: Optional[str] = None
) -> str:
    """Format user link (backward compatible)"""
    return link_formatter.format_user_link(user_id, username, full_name)


def format_channel_link(
    channel_id: int, channel_title: Optional[str] = None, channel_username: Optional[str] = None
) -> str:
    """Format channel link (backward compatible)"""
    return link_formatter.format_channel_link(channel_id, channel_title, channel_username)


def format_vk_post_link(owner_id: int, post_id: int) -> str:
    """Format VK post link"""
    return link_formatter.format_vk_post_link(owner_id, post_id)


def format_vk_group_link(group_id: int, screen_name: Optional[str] = None) -> str:
    """Format VK group link"""
    return link_formatter.format_vk_group_link(group_id, screen_name)
