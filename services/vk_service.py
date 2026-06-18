"""
VK Service with retry logic and single session - Updated
Сервис VK с retry логикой и единой сессией - Обновлённый
"""

import asyncio
from typing import Any, Dict, List, Optional

import aiohttp
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

import config
from utils.logger import logger
from utils.ssl_helper import get_ssl_param

from .queue_manager import vk_queue

logger = logger.bind(module="vk_service")


class VKService:
    """Service for VK API operations with automatic retry"""

    def __init__(self):
        self.token = config.config.vk_token
        self.version = config.config.vk_api_version
        self.api_url = config.config.vk_api_url
        self._session = None
        self._session_lock = asyncio.Lock()

    # =====
    # Session management with lazy initialization
    # Управление сессией с отложенной инициализацией
    # =====

    async def _ensure_session(self):
        """Ensure session is initialized (lazy initialization)"""
        if self._session is None:
            async with self._session_lock:
                if self._session is None:
                    await self.init_session()

    async def init_session(self):
        """Initialize aiohttp session"""

        if not self._session:
            timeout = aiohttp.ClientTimeout(total=60, connect=10, sock_read=30)
            self._session = aiohttp.ClientSession(timeout=timeout)
            logger.info("vk_session_initialized")

    async def close_session(self):
        """Close aiohttp session"""

        if self._session:
            await self._session.close()
            self._session = None
            logger.info("vk_session_closed")

    # =====
    # API request with retry
    # API запрос с повторами
    # =====

    @retry(
        stop=stop_after_attempt(5),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((aiohttp.ClientError, asyncio.TimeoutError)),
        reraise=True,
    )
    async def _make_request(self, method: str, params: Dict[str, Any]) -> Optional[Dict]:
        """Make VK API request with automatic retry"""

        await self._ensure_session()

        # Copy params so the caller's dict is not mutated / Копируем params, чтобы не мутировать словарь вызывающего
        request_params = {**params, "access_token": self.token, "v": self.version}

        url = f"{self.api_url}{method}"

        async def _do_request():
            async with self._session.get(
                url, params=request_params, ssl=get_ssl_param()
            ) as response:
                return await response.json()

        # Rate-limit VK requests through the shared queue / Ограничиваем частоту запросов через общую очередь
        data = await vk_queue.execute(_do_request)

        if "error" in data:
            error_code = data["error"].get("error_code")
            error_msg = data["error"].get("error_msg", "Unknown error")

            if error_code == 6:
                logger.warning("vk_rate_limit", method=method)
                raise aiohttp.ClientError(f"VK Rate Limit: {error_msg}")

            logger.error("vk_api_error", method=method, error=error_msg, error_code=error_code)
            return None

        return data.get("response")

    # =====
    # Group operations
    # Операции с группами
    # =====

    async def get_group_id(self, screen_name: str) -> Optional[int]:
        """Get group ID by screen name"""

        response = await self._make_request("groups.getById", {"group_id": screen_name})

        if response and len(response) > 0:
            return response[0].get("id")
        return None

    async def validate_group_access(self, group_id: int) -> bool:
        """Validate access to group"""

        posts = await self.get_posts(group_id, count=1)
        return posts is not None

    async def get_group_photo(self, group_id: int, size: str = "photo_200") -> Optional[str]:
        """
        Get group avatar URL
        size: photo_50, photo_100, photo_200 (default)
        """

        response = await self._make_request(
            "groups.getById", {"group_id": group_id, "fields": size}
        )

        if response and len(response) > 0:
            return response[0].get(size)
        return None

    async def get_group_info(self, group_id: int) -> Optional[Dict]:
        """
        Get full group information including avatar
        Returns dict with id, name, screen_name, photo_50, photo_100, photo_200
        """

        response = await self._make_request(
            "groups.getById", {"group_id": group_id, "fields": "photo_50,photo_100,photo_200"}
        )

        if response and len(response) > 0:
            group_data = response[0]
            return {
                "id": group_data.get("id"),
                "name": group_data.get("name"),
                "screen_name": group_data.get("screen_name"),
                "photo_50": group_data.get("photo_50"),
                "photo_100": group_data.get("photo_100"),
                "photo_200": group_data.get("photo_200"),
            }
        return None

    # =====
    # Wall operations
    # Операции со стеной
    # =====

    async def get_posts(
        self, owner_id: int, count: int = 100, offset: int = 0
    ) -> Optional[List[Dict]]:
        """Get wall posts"""

        if owner_id > 0:
            owner_id = -owner_id

        response = await self._make_request(
            "wall.get",
            {
                "owner_id": owner_id,
                "count": min(count, 100),
                "offset": offset,
                "filter": "owner",
                "extended": 1,
            },
        )

        if response and "items" in response:
            return response["items"]
        return None

    async def get_new_posts(self, owner_id: int, last_post_id: Optional[int]) -> List[Dict]:
        """Get new posts since last_post_id"""

        posts = await self.get_posts(owner_id, count=100)

        if not posts:
            return []

        new_posts = []
        for post in posts:
            post_id = post.get("id")

            if last_post_id and post_id <= last_post_id:
                continue

            if post.get("is_pinned"):
                continue

            if post.get("marked_as_ads"):
                continue

            if "copy_history" in post:
                continue

            new_posts.append(post)

        return list(reversed(new_posts))

    async def get_post_comments(self, owner_id: int, post_id: int, count: int = 5) -> List[Dict]:
        """Get comments for post"""

        if owner_id > 0:
            owner_id = -owner_id

        response = await self._make_request(
            "wall.getComments",
            {
                "owner_id": owner_id,
                "post_id": post_id,
                "count": count,
                "sort": "asc",
                "extended": 1,
            },
        )

        if response and "items" in response:
            return response["items"]
        return []

    # =====
    # Helper methods
    # Вспомогательные методы
    # =====

    def _is_duplicate(self, item_id: Any, seen_set: set, item_type: str) -> bool:
        """Check if item is duplicate and add to seen set"""

        if not item_id:
            return False

        if item_id in seen_set:
            logger.debug("duplicate_found", item_type=item_type, item_id=str(item_id))
            return True

        seen_set.add(item_id)
        return False

    # =====
    # Attachment parsing
    # Парсинг вложений
    # =====

    def parse_attachments(self, post: Dict) -> Dict:
        """Parse post attachments"""

        result = {
            "photos": [],
            "videos": [],
            "audios": [],
            "docs": [],
            "gifs": [],
            "articles": [],
            "audio_playlists": [],
        }

        seen_photo_ids = set()
        seen_video_ids = set()
        seen_audio_ids = set()
        seen_doc_ids = set()
        seen_article_ids = set()
        seen_playlist_ids = set()

        attachments = post.get("attachments", [])

        for attachment in attachments:
            att_type = attachment.get("type")

            if att_type == "photo":
                self._process_photo_attachment(attachment, result, seen_photo_ids)
            elif att_type == "video":
                self._process_video_attachment(attachment, result, seen_video_ids)
            elif att_type == "audio":
                self._process_audio_attachment(attachment, result, seen_audio_ids)
            elif att_type == "doc":
                self._process_doc_attachment(attachment, result, seen_doc_ids)
            elif att_type == "link":
                self._process_link_attachment(attachment, result, seen_article_ids)
            elif att_type == "article":
                self._process_article_attachment(attachment, result, seen_article_ids)
            elif att_type == "audio_playlist":
                self._process_audio_playlist_attachment(attachment, result, seen_playlist_ids)

        return result

    def _process_photo_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """Process photo attachment"""
        photo = attachment.get("photo", {})
        photo_id = photo.get("id")

        if self._is_duplicate(photo_id, seen_ids, "photo"):
            return

        sizes = photo.get("sizes", [])
        if sizes:
            largest = max(sizes, key=lambda x: x.get("width", 0) * x.get("height", 0))
            result["photos"].append(
                {
                    "url": largest.get("url"),
                    "width": largest.get("width"),
                    "height": largest.get("height"),
                }
            )

    def _process_video_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """Process video attachment"""
        video = attachment.get("video", {})
        video_id = video.get("id")
        owner_id = video.get("owner_id")
        video_key = f"{owner_id}_{video_id}"

        if self._is_duplicate(video_key, seen_ids, "video"):
            return

        result["videos"].append(
            {
                "id": video_id,
                "owner_id": owner_id,
                "title": video.get("title", "Video"),
                "duration": video.get("duration"),
                "access_key": video.get("access_key"),
            }
        )

    def _process_audio_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """Process audio attachment"""
        audio = attachment.get("audio", {})
        audio_id = audio.get("id")
        owner_id = audio.get("owner_id")
        audio_key = f"{owner_id}_{audio_id}"

        if self._is_duplicate(audio_key, seen_ids, "audio"):
            return

        result["audios"].append(
            {
                "artist": audio.get("artist", "Unknown"),
                "title": audio.get("title", "Unknown"),
                "url": audio.get("url"),
                "duration": audio.get("duration"),
            }
        )

    def _process_doc_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """Process document attachment (GIF docs are routed to a dedicated list)"""
        doc = attachment.get("doc", {})
        doc_id = doc.get("id")

        if self._is_duplicate(doc_id, seen_ids, "doc"):
            return

        ext = (doc.get("ext", "") or "").lower()
        item = {
            "title": doc.get("title", "Document"),
            "ext": doc.get("ext", ""),
            "size": doc.get("size", 0),
            "url": doc.get("url"),
        }

        # GIF/animation is sent as a Telegram animation (so it can carry text caption)
        # GIF отправляется как анимация Telegram (чтобы её можно было совместить с текстом)
        if ext == "gif" or doc.get("type") == 3:
            result["gifs"].append(item)
        else:
            result["docs"].append(item)

    def _process_link_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """Process link attachment"""
        link = attachment.get("link", {})
        link_url = link.get("url", "")

        if not ("@" in link_url or "vk.com/@" in link_url or link.get("target_object")):
            return

        photo_url = self._extract_photo_from_link(link)
        link_id = link.get("id")

        if self._is_duplicate(link_id, seen_ids, "article"):
            return

        result["articles"].append(
            {
                "title": link.get("title", "Article"),
                "subtitle": link.get("description", ""),
                "url": link_url,
                "photo_url": photo_url,
            }
        )

    def _process_article_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """Process article attachment"""
        article = attachment.get("article", {})
        article_id = article.get("id")

        if self._is_duplicate(article_id, seen_ids, "article"):
            return

        photo_url = self._extract_photo_from_dict(article, "photo")

        result["articles"].append(
            {
                "title": article.get("title", "Article"),
                "subtitle": article.get("subtitle", ""),
                "url": article.get("url", ""),
                "photo_url": photo_url,
            }
        )

    def _process_audio_playlist_attachment(self, attachment: Dict, result: Dict, seen_ids: set):
        """
        Process audio playlist attachment
        Structure: {
            "type": "audio_playlist",
            "audio_playlist": {
                "id": int,
                "owner_id": int,
                "title": str,
                "description": str,
                "count": int,
                "photo": {
                    "photo_34": url,
                    "photo_68": url,
                    "photo_135": url,
                    "photo_270": url,
                    "photo_300": url,
                    "photo_600": url
                },
                "access_key": str
            }
        }
        """
        playlist = attachment.get("audio_playlist", {})
        playlist_id = playlist.get("id")
        owner_id = playlist.get("owner_id")
        playlist_key = f"{owner_id}_{playlist_id}"

        if self._is_duplicate(playlist_key, seen_ids, "audio_playlist"):
            return

        result["audio_playlists"].append(
            {
                "id": playlist_id,
                "owner_id": owner_id,
                "title": playlist.get("title", "Плейлист"),
                "description": playlist.get("description", ""),
                "count": playlist.get("count", 0),
                "photo": playlist.get("photo", {}),
                "access_key": playlist.get("access_key", ""),
            }
        )

    def _extract_photo_from_link(self, link: Dict) -> Optional[str]:
        """Extract photo URL from link object"""
        photo_url = None

        if "photo" in link and link["photo"]:
            photo_url = self._extract_photo_from_dict(link["photo"], "sizes")

        if not photo_url and "image" in link:
            photo_url = self._extract_photo_from_dict(link["image"], "sizes")

        return photo_url

    def _extract_photo_from_dict(self, data: Dict, sizes_key: str = "sizes") -> Optional[str]:
        """Extract largest photo URL from dict with sizes"""
        if isinstance(data, dict) and sizes_key in data:
            sizes = data[sizes_key]
            if sizes:
                largest = max(sizes, key=lambda x: x.get("width", 0) * x.get("height", 0))
                return largest.get("url")
        return None
