"""
Telegram Service with HTML parse mode and global timeouts
Сервис Telegram с HTML parse mode и глобальными таймаутами
"""

import asyncio
from typing import Dict, List, Optional, Tuple, Union

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.types import FSInputFile, InputMediaAudio, InputMediaPhoto, InputMediaVideo, Message

import config
from utils.helpers import format_text_for_telegram
from utils.logger import logger
from utils.messages import Messages
from utils.retry_helper import TELEGRAM_API_STRATEGY, retry_telegram_api

from .queue_manager import telegram_channel_queue, telegram_queue

logger = logger.bind(module="telegram_service")


class TelegramService:
    """Service for Telegram Bot API operations"""

    def __init__(self, bot: Bot):
        self.bot = bot

    # =====
    # Channel validation
    # Валидация канала
    # =====

    async def validate_channel_access(self, channel_id: Union[int, str]) -> bool:
        """Validate bot has access to channel"""

        try:
            msg = await self.bot.send_message(
                channel_id, Messages.CHANNEL_ACCESS_PROBE, parse_mode="HTML"
            )

            await self.bot.delete_message(channel_id, msg.message_id)
            logger.info("channel_access_validated", channel_id=channel_id)
            return True

        except Exception as e:
            logger.error("channel_validation_failed", channel_id=channel_id, error=str(e))
            return False

    async def check_channel_admin_rights(self, channel_id: Union[int, str]) -> bool:
        """Check if bot has admin rights in channel"""

        try:
            chat_member = await self.bot.get_chat_member(channel_id, self.bot.id)
            return chat_member.status in ["administrator", "creator"]
        except Exception as e:
            logger.warning("admin_rights_check_failed", error=str(e))
            return False

    # =====
    # Channel avatar management
    # Управление аватаром канала
    # =====

    async def update_channel_avatar(self, channel_id: Union[int, str], photo_path: str) -> bool:
        """
        Update channel avatar/photo
        Returns: True if successful, False otherwise
        """

        try:
            photo = FSInputFile(photo_path)

            await self.bot.set_chat_photo(chat_id=channel_id, photo=photo)

            logger.info("channel_avatar_updated", channel_id=channel_id)
            return True

        except TelegramBadRequest as e:
            error_msg = str(e)
            if "not enough rights" in error_msg.lower():
                logger.error("channel_avatar_no_rights", channel_id=channel_id)
            else:
                logger.error("channel_avatar_update_failed", channel_id=channel_id, error=error_msg)
            return False

        except Exception as e:
            logger.error("channel_avatar_unexpected_error", channel_id=channel_id, error=str(e))
            return False

    async def get_channel_info(self, channel_id: Union[int, str]) -> Optional[Dict]:
        """
        Get channel information
        Returns: dict with id, title, username, photo
        """

        try:
            chat = await self.bot.get_chat(channel_id)

            return {
                "id": chat.id,
                "title": chat.title,
                "username": chat.username,
                "photo": chat.photo,
            }

        except Exception as e:
            logger.error("channel_info_failed", channel_id=channel_id, error=str(e))
            return None

    # =====
    # Send messages with standardized return
    # Отправка сообщений со стандартизированным возвратом
    # =====

    async def send_message(
        self,
        chat_id: Union[int, str],
        text: str,
        reply_to: Optional[int] = None,
        parse_mode: str = "HTML",
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Send text message with global timeout
        Returns: (message, retry_after_seconds)
        """

        try:

            async def _send():
                return await self.bot.send_message(
                    chat_id,
                    text,
                    reply_to_message_id=reply_to,
                    parse_mode=parse_mode,
                    disable_web_page_preview=True,
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msg, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msg, retry_after)

        except Exception as e:
            logger.error("telegram_send_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    # =====
    # Send photos
    # Отправка фото
    # =====

    async def send_photo(
        self,
        chat_id: Union[int, str],
        photo_path: str,
        caption: str = None,
        parse_mode: str = "HTML",
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Send photo with global timeout
        Returns: (message, retry_after_seconds)
        """

        try:
            photo = FSInputFile(photo_path)

            if caption and len(caption) > config.config.tg_max_caption_length:
                caption = caption[: config.config.tg_max_caption_length]

            async def _send():
                return await self.bot.send_photo(
                    chat_id,
                    photo,
                    caption=caption,
                    parse_mode=parse_mode if caption else None,
                    reply_to_message_id=reply_to,
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msg, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msg, retry_after)

        except Exception as e:
            logger.error("telegram_photo_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    async def send_media_group(
        self,
        chat_id: Union[int, str],
        photos: List[str],
        caption: str = None,
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[List[Message]], Optional[int]]:
        """
        Send photo album with global timeout
        Returns: (messages, retry_after_seconds)
        """

        try:
            media = []
            photos = photos[: config.config.tg_media_group_limit]

            for i, photo_path in enumerate(photos):
                photo = FSInputFile(photo_path)

                photo_caption = None
                if i == 0 and caption:
                    photo_caption = caption
                    if len(photo_caption) > config.config.tg_max_caption_length:
                        photo_caption = photo_caption[: config.config.tg_max_caption_length]

                media.append(
                    InputMediaPhoto(
                        media=photo,
                        caption=photo_caption,
                        parse_mode="HTML" if photo_caption else None,
                    )
                )

            async def _send():
                return await self.bot.send_media_group(chat_id, media, reply_to_message_id=reply_to)

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msgs, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msgs, retry_after)

        except Exception as e:
            logger.error("telegram_media_group_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    # =====
    # Send video
    # Отправка видео
    # =====

    async def send_video(
        self,
        chat_id: Union[int, str],
        video_path: str,
        caption: str = None,
        parse_mode: str = "HTML",
        width: int = None,
        height: int = None,
        thumbnail: str = None,
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Send video with adaptive timeout
        Returns: (message, retry_after_seconds)
        """

        try:
            video = FSInputFile(video_path)
            thumb = FSInputFile(thumbnail) if thumbnail else None

            if caption and len(caption) > config.config.tg_max_caption_length:
                caption = caption[: config.config.tg_max_caption_length]

            import os

            file_size = os.path.getsize(video_path)
            timeout_seconds = max(60, int((file_size / (1024 * 1024)) * 1.5 + 30))
            timeout_seconds = min(timeout_seconds, 600)

            logger.debug(
                "video_send_timeout",
                file_size_mb=file_size / (1024 * 1024),
                timeout=timeout_seconds,
            )

            async def _send():
                return await self.bot.send_video(
                    chat_id,
                    video,
                    caption=caption,
                    parse_mode=parse_mode if caption else None,
                    width=width,
                    height=height,
                    thumbnail=thumb,
                    supports_streaming=True,
                    request_timeout=timeout_seconds,
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msg, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msg, retry_after)

        except Exception as e:
            logger.error("telegram_video_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    async def send_video_group(
        self,
        chat_id: Union[int, str],
        videos: List[Dict],
        caption: str = None,
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[List[Message]], Optional[int]]:
        """
        Send video album with adaptive timeout
        videos: List of dicts with 'path', 'width', 'height', 'thumbnail'
        Returns: (messages, retry_after_seconds)
        """

        try:
            media = []
            videos = videos[: config.config.tg_media_group_limit]

            import os

            max_file_size = max((os.path.getsize(v["path"]) for v in videos), default=0)
            timeout_seconds = max(90, int((max_file_size / (1024 * 1024)) * 1.5 + 30))
            timeout_seconds = min(timeout_seconds, 600)

            logger.debug(
                "video_group_timeout",
                max_size_mb=max_file_size / (1024 * 1024),
                timeout=timeout_seconds,
            )

            for i, video_info in enumerate(videos):
                video = FSInputFile(video_info["path"])
                thumb = (
                    FSInputFile(video_info["thumbnail"]) if video_info.get("thumbnail") else None
                )

                video_caption = None
                if i == 0 and caption:
                    video_caption = caption
                    if len(video_caption) > config.config.tg_max_caption_length:
                        video_caption = video_caption[: config.config.tg_max_caption_length]

                media.append(
                    InputMediaVideo(
                        media=video,
                        caption=video_caption,
                        parse_mode="HTML" if video_caption else None,
                        width=video_info.get("width"),
                        height=video_info.get("height"),
                        thumbnail=thumb,
                        supports_streaming=True,
                    )
                )

            async def _send():
                return await self.bot.send_media_group(
                    chat_id, media, reply_to_message_id=reply_to, request_timeout=timeout_seconds
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msgs, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msgs, retry_after)

        except Exception as e:
            logger.error("telegram_video_group_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    # =====
    # Send audio
    # Отправка аудио
    # =====

    async def send_audio(
        self,
        chat_id: Union[int, str],
        audio_path: str,
        title: str = None,
        performer: str = None,
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Send audio with timeout
        Returns: (message, retry_after_seconds)
        """

        try:
            audio = FSInputFile(audio_path)

            import os

            file_size = os.path.getsize(audio_path)
            timeout_seconds = max(60, int((file_size / (1024 * 1024)) * 2 + 20))
            timeout_seconds = min(timeout_seconds, 300)

            async def _send():
                return await self.bot.send_audio(
                    chat_id,
                    audio,
                    title=title,
                    performer=performer,
                    reply_to_message_id=reply_to,
                    request_timeout=timeout_seconds,
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msg, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msg, retry_after)

        except Exception as e:
            logger.error("telegram_audio_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    async def send_audio_group(
        self, chat_id: Union[int, str], audios: List[Dict], reply_to: Optional[int] = None
    ) -> Tuple[Optional[List[Message]], Optional[int]]:
        """
        Send multiple audio files as a single album (one message)
        audios: List of dicts with 'path', 'title', 'performer'
        Returns: (messages, retry_after_seconds)
        """

        try:
            media = []
            audios = audios[: config.config.tg_media_group_limit]

            import os

            max_file_size = max((os.path.getsize(a["path"]) for a in audios), default=0)
            timeout_seconds = max(60, int((max_file_size / (1024 * 1024)) * 2 + 20))
            timeout_seconds = min(timeout_seconds, 300)

            for audio_info in audios:
                audio = FSInputFile(audio_info["path"])
                media.append(
                    InputMediaAudio(
                        media=audio,
                        title=audio_info.get("title"),
                        performer=audio_info.get("performer"),
                    )
                )

            async def _send():
                return await self.bot.send_media_group(
                    chat_id, media, reply_to_message_id=reply_to, request_timeout=timeout_seconds
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msgs, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msgs, retry_after)

        except Exception as e:
            logger.error("telegram_audio_group_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    # =====
    # Send animation (GIF)
    # Отправка анимации (GIF)
    # =====

    async def send_animation(
        self,
        chat_id: Union[int, str],
        animation_path: str,
        caption: str = None,
        reply_to: Optional[int] = None,
        parse_mode: str = "HTML",
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Send animation/GIF with optional caption (text + GIF in one message)
        Returns: (message, retry_after_seconds)
        """

        try:
            animation = FSInputFile(animation_path)

            if caption and len(caption) > config.config.tg_max_caption_length:
                caption = caption[: config.config.tg_max_caption_length]

            async def _send():
                return await self.bot.send_animation(
                    chat_id,
                    animation,
                    caption=caption,
                    parse_mode=parse_mode if caption else None,
                    reply_to_message_id=reply_to,
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msg, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msg, retry_after)

        except Exception as e:
            logger.error("telegram_animation_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    # =====
    # Send document
    # Отправка документа
    # =====

    async def send_document(
        self,
        chat_id: Union[int, str],
        document_path: str,
        caption: str = None,
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[Message], Optional[int]]:
        """
        Send document with timeout
        Returns: (message, retry_after_seconds)
        """

        try:
            document = FSInputFile(document_path)

            if caption and len(caption) > config.config.tg_max_caption_length:
                caption = caption[: config.config.tg_max_caption_length]

            import os

            file_size = os.path.getsize(document_path)
            timeout_seconds = max(60, int((file_size / (1024 * 1024)) * 2 + 20))
            timeout_seconds = min(timeout_seconds, 300)

            async def _send():
                return await self.bot.send_document(
                    chat_id,
                    document,
                    caption=caption,
                    parse_mode="HTML" if caption else None,
                    reply_to_message_id=reply_to,
                    request_timeout=timeout_seconds,
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msg, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msg, retry_after)

        except Exception as e:
            logger.error("telegram_document_failed", chat_id=chat_id, error=str(e))
            return (None, None)

    # =====
    # Send mixed photo+video groups
    # Отправка смешанных фото+видео групп
    # =====

    async def send_mixed_media_group(
        self,
        chat_id: Union[int, str],
        videos: List[Dict],
        photos: List[str],
        caption: str = None,
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[List[Message]], Optional[int]]:
        """
        Send mixed photo+video album with adaptive timeout
        videos: List of dicts with 'path', 'width', 'height', 'thumbnail'
        photos: List of photo paths
        Returns: (messages, retry_after_seconds)
        """

        try:
            media = []
            total_items = len(videos) + len(photos)

            if total_items > config.config.tg_media_group_limit:
                logger.warning("mixed_media_exceeds_limit", videos=len(videos), photos=len(photos))
                videos = videos[: config.config.tg_media_group_limit]
                photos = []

            import os

            max_file_size = 0

            # Добавляем видео первыми (приоритет)
            for i, video_info in enumerate(videos):
                video = FSInputFile(video_info["path"])
                thumb = (
                    FSInputFile(video_info["thumbnail"]) if video_info.get("thumbnail") else None
                )

                file_size = os.path.getsize(video_info["path"])
                max_file_size = max(max_file_size, file_size)

                video_caption = None
                if i == 0 and caption:
                    video_caption = caption
                    if len(video_caption) > config.config.tg_max_caption_length:
                        video_caption = video_caption[: config.config.tg_max_caption_length]

                media.append(
                    InputMediaVideo(
                        media=video,
                        caption=video_caption,
                        parse_mode="HTML" if video_caption else None,
                        width=video_info.get("width"),
                        height=video_info.get("height"),
                        thumbnail=thumb,
                        supports_streaming=True,
                    )
                )

            # Добавляем фото после видео
            for photo_path in photos:
                photo = FSInputFile(photo_path)
                media.append(InputMediaPhoto(media=photo))

            # Адаптивный таймаут
            timeout_seconds = max(90, int((max_file_size / (1024 * 1024)) * 1.5 + 30))
            timeout_seconds = min(timeout_seconds, 600)

            logger.debug(
                "mixed_media_timeout",
                videos=len(videos),
                photos=len(photos),
                max_size_mb=max_file_size / (1024 * 1024),
                timeout=timeout_seconds,
            )

            async def _send():
                return await self.bot.send_media_group(
                    chat_id, media, reply_to_message_id=reply_to, request_timeout=timeout_seconds
                )

            channel_id = chat_id if isinstance(chat_id, int) else 0
            msgs, retry_after = await retry_telegram_api(
                lambda: telegram_channel_queue.execute(channel_id, _send)
            )

            return (msgs, retry_after)

        except Exception as e:
            logger.error("telegram_mixed_media_failed", chat_id=chat_id, error=str(e))
            return (None, None)
