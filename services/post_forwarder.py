"""
Post Forwarder with HTML formatting - Optimized version
Пересыльщик постов с HTML форматированием - Оптимизированная версия
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from aiogram.types import Message

import config
from utils.helpers import escape_html, format_text_for_telegram
from utils.logger import logger
from utils.messages import Messages

from .media_handler import MediaHandler
from .telegram_service import TelegramService
from .vk_service import VKService

logger = logger.bind(module="post_forwarder")


def _reply_id(main_message) -> Optional[int]:
    """Extract a message_id usable as reply target from a Message or list of Messages"""
    if not main_message:
        return None
    if isinstance(main_message, list):
        return main_message[0].message_id if main_message else None
    return main_message.message_id


class PostForwarder:
    """Service for forwarding VK posts to Telegram"""

    def __init__(
        self, vk_service: VKService, telegram_service: TelegramService, media_handler: MediaHandler
    ):
        self.vk = vk_service
        self.tg = telegram_service
        self.media = media_handler

    async def forward_post(self, post: dict, tg_id: int) -> Tuple[bool, bool, Optional[int]]:
        """
        Forward VK post to Telegram
        Returns: (success, is_flood_wait, retry_after_seconds)
        """
        main_message = None
        downloaded_files = []
        is_flood_wait = False
        retry_after = None
        attachments_delivered = False

        try:
            text = post.get("text", "")
            attachments = self.vk.parse_attachments(post)

            photos = attachments.get("photos", [])
            videos = attachments.get("videos", [])
            audios = attachments.get("audios", [])
            docs = attachments.get("docs", [])
            gifs = attachments.get("gifs", [])
            articles = attachments.get("articles", [])
            audio_playlists = attachments.get("audio_playlists", [])

            post_id = post.get("id")
            logger.debug(
                "post_processing",
                post_id=post_id,
                text_len=len(text),
                photos=len(photos),
                videos=len(videos),
                audios=len(audios),
                docs=len(docs),
                gifs=len(gifs),
                articles=len(articles),
                playlists=len(audio_playlists),
            )

            def _merge_flood(flood, retry):
                nonlocal is_flood_wait, retry_after
                if flood:
                    is_flood_wait, retry_after = True, retry

            # Strategy 1: Article is always the main message / Статья всегда главное сообщение
            if articles:
                main_message, flood, retry = await self._send_articles(
                    tg_id, articles, downloaded_files
                )
                _merge_flood(flood, retry)

                if main_message:
                    if text:
                        flood, retry = await self._send_reply_text(tg_id, text, main_message)
                        _merge_flood(flood, retry)

                    # Photos/videos as a reply album / Фото-видео ответом
                    _, flood, retry = await self._send_media_as_reply(
                        tg_id, photos, videos, main_message, downloaded_files
                    )
                    _merge_flood(flood, retry)

                    # GIFs as reply / GIF ответом
                    flood, retry = await self._send_gifs_as_reply(
                        tg_id, gifs, _reply_id(main_message), downloaded_files
                    )
                    _merge_flood(flood, retry)

                    delivered, flood, retry = await self._send_attachments(
                        tg_id, audios, docs, audio_playlists, main_message, downloaded_files
                    )
                    attachments_delivered = attachments_delivered or delivered
                    _merge_flood(flood, retry)

            # Strategy 2: Photos/videos are the main message / Фото-видео главное сообщение
            elif photos or videos:
                caption_text, reply_texts = self._smart_split_text(text)

                main_message, flood, retry = await self._send_mixed_media(
                    tg_id, photos, videos, caption_text, downloaded_files
                )
                _merge_flood(flood, retry)

                if main_message:
                    if reply_texts:
                        flood, retry = await self._send_text_parts_reply(
                            tg_id, reply_texts, main_message
                        )
                        _merge_flood(flood, retry)

                    flood, retry = await self._send_gifs_as_reply(
                        tg_id, gifs, _reply_id(main_message), downloaded_files
                    )
                    _merge_flood(flood, retry)

                    delivered, flood, retry = await self._send_attachments(
                        tg_id, audios, docs, audio_playlists, main_message, downloaded_files
                    )
                    attachments_delivered = attachments_delivered or delivered
                    _merge_flood(flood, retry)

            # Strategy 3: GIF(s) + text in one message / GIF и текст в одном сообщении
            elif gifs:
                main_message, flood, retry = await self._send_gifs(
                    tg_id, gifs, text, downloaded_files
                )
                _merge_flood(flood, retry)

                # GIF download failed but there is text - at least deliver the text
                if main_message is None and text:
                    main_message, flood, retry = await self._send_text_only(tg_id, text)
                    _merge_flood(flood, retry)

                if main_message:
                    delivered, flood, retry = await self._send_attachments(
                        tg_id, audios, docs, audio_playlists, main_message, downloaded_files
                    )
                    attachments_delivered = attachments_delivered or delivered
                    _merge_flood(flood, retry)

            # Strategy 4: Text only / Только текст
            elif text:
                main_message, flood, retry = await self._send_text_only(tg_id, text)
                _merge_flood(flood, retry)

                if main_message:
                    delivered, flood, retry = await self._send_attachments(
                        tg_id, audios, docs, audio_playlists, main_message, downloaded_files
                    )
                    attachments_delivered = attachments_delivered or delivered
                    _merge_flood(flood, retry)

            # Strategy 5: Attachments only / Только вложения
            else:
                delivered, flood, retry = await self._send_attachments(
                    tg_id, audios, docs, audio_playlists, None, downloaded_files
                )
                attachments_delivered = delivered
                _merge_flood(flood, retry)

            success = main_message is not None or attachments_delivered

        except Exception as e:
            post_id = post.get("id", "unknown")
            owner_id = post.get("owner_id", "unknown")
            logger.error(
                "post_forward_critical_error", post_id=post_id, owner_id=owner_id, error=str(e)
            )
            # If the main message was already delivered, treat as success to avoid
            # re-sending it (duplicate) on the next retry.
            # Если главное сообщение уже доставлено - считаем успехом, чтобы не дублировать при повторе.
            success = main_message is not None or attachments_delivered

        finally:
            if downloaded_files:
                try:
                    await self.media.cleanup_files(downloaded_files)
                except Exception as e:
                    logger.warning("cleanup_failed", error=str(e))

        return (success, is_flood_wait, retry_after)

    # =====
    # Smart text splitting
    # Умное деление текста
    # =====

    def _smart_split_text(
        self, text: str, max_caption: int = 1024
    ) -> Tuple[Optional[str], List[str]]:
        """
        Smart text splitting: max in caption, rest in reply
        Splits by paragraphs for readability
        Returns: (caption_text, reply_texts_list)
        """
        if not text:
            return (None, [])

        if len(text) <= max_caption:
            return (format_text_for_telegram(text), [])

        paragraphs = text.split("\n\n")
        caption = ""
        remaining = []
        caption_filled = False

        for para in paragraphs:
            if not caption_filled and len(caption) + len(para) + 2 <= max_caption:
                caption += para + "\n\n"
            else:
                # Once the caption is full, everything else must go to reply,
                # preserving order (don't pull later short paragraphs into the caption).
                caption_filled = True
                remaining.append(para)

        # Build reply messages from leftover paragraphs
        reply_messages = []
        current_msg = ""

        for para in remaining:
            if len(current_msg) + len(para) + 2 <= 4096:
                current_msg += para + "\n\n"
            else:
                if current_msg:
                    reply_messages.append(format_text_for_telegram(current_msg.strip()))
                current_msg = para + "\n\n"

        if current_msg:
            reply_messages.append(format_text_for_telegram(current_msg.strip()))

        caption_formatted = format_text_for_telegram(caption.strip()) if caption.strip() else None
        return (caption_formatted, reply_messages[:4])

    # =====
    # Send articles
    # Отправка статей
    # =====

    async def _send_articles(
        self, tg_id: int, articles: List[Dict], downloaded_files: List[str]
    ) -> Tuple[Optional[Message], bool, Optional[int]]:
        """Send articles - always main message"""
        main_message = None
        is_flood_wait = False
        retry_after = None

        for article in articles:
            try:
                article_msg, article_retry = await self._send_article(
                    tg_id, article, None, downloaded_files
                )
                if article_msg:
                    if not main_message:
                        main_message = article_msg
                elif article_retry:
                    is_flood_wait = True
                    retry_after = article_retry
                await asyncio.sleep(1)
            except Exception as e:
                logger.error("article_send_failed", error=str(e))

        return (main_message, is_flood_wait, retry_after)

    async def _send_article(
        self, chat_id: int, article: dict, reply_to: Optional[int], downloaded_files: List[str]
    ) -> Tuple[Optional[Message], Optional[int]]:
        """Send article as preview + link"""
        try:
            # NOTE: build raw text and escape exactly once via format_text_for_telegram.
            # Не экранируем заголовок отдельно - format_text_for_telegram делает это один раз
            # (двойное экранирование давало литералы вида "&amp;").
            title = article.get("title") or Messages.ARTICLE_DEFAULT_TITLE
            article_url = article.get("url", "") or article.get("view_url", "")
            photo_url = article.get("photo_url")

            article_text = Messages.ARTICLE_TITLE.format(title=title)
            if article_url:
                article_text += Messages.ARTICLE_READ_LINK.format(url=article_url)

            article_text = format_text_for_telegram(article_text)

            if photo_url:
                photo_path = await self.media.download_photo(
                    photo_url, f"article_preview_{abs(hash(photo_url))}.jpg"
                )

                if photo_path:
                    downloaded_files.append(photo_path)
                    result, retry_after = await self.tg.send_photo(
                        chat_id, photo_path, caption=article_text
                    )
                    if result:
                        logger.debug("article_sent_with_preview")
                    return (result, retry_after)

            result, retry_after = await self.tg.send_message(
                chat_id, article_text, reply_to=reply_to
            )
            return (result, retry_after)

        except Exception as e:
            logger.error("article_send_error", error=str(e), exc_info=True)
            return (None, None)

    # =====
    # Send mixed photo+video media
    # Отправка смешанного фото+видео
    # =====

    async def _send_mixed_media(
        self,
        tg_id: int,
        photos: List[Dict],
        videos: List[Dict],
        caption_text: Optional[str],
        downloaded_files: List[str],
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[Message], bool, Optional[int]]:
        """
        Send photos and videos as mixed album (Telegram supports this!)
        Priority: videos first, then photos up to limit of 10
        """
        if not photos and not videos:
            return (None, False, None)

        # Download videos
        video_data = []
        failed_videos = []

        for video in videos[: config.config.tg_media_group_limit]:
            video_info = await self.media.download_vk_video(
                video.get("owner_id"), video.get("id"), video.get("access_key")
            )

            if video_info and video_info.get("path"):
                video_data.append(video_info)
                downloaded_files.append(video_info["path"])
                if video_info.get("thumbnail"):
                    downloaded_files.append(video_info["thumbnail"])
            else:
                failed_videos.append(video)

        # Download photos (up to limit)
        photo_paths = []
        remaining_slots = config.config.tg_media_group_limit - len(video_data)

        for photo in photos[:remaining_slots]:
            photo_path = await self.media.download_photo(photo.get("url"))
            if photo_path:
                photo_paths.append(photo_path)
                downloaded_files.append(photo_path)

        main_message = None
        is_flood_wait = False
        retry_after = None

        if video_data and photo_paths:
            try:
                msg, msg_retry = await self.tg.send_mixed_media_group(
                    tg_id, video_data, photo_paths, caption_text, reply_to=reply_to
                )
                if msg:
                    main_message = msg
                    logger.debug(
                        "mixed_media_sent", videos=len(video_data), photos=len(photo_paths)
                    )
                elif msg_retry:
                    is_flood_wait, retry_after = True, msg_retry
            except Exception as e:
                logger.error("mixed_media_failed", error=str(e))
                # Fallback: send separately
                msg, flood, retry = await self._send_videos_only(
                    tg_id, video_data, caption_text, reply_to
                )
                if msg:
                    main_message = msg
                if flood:
                    is_flood_wait, retry_after = True, retry

                if photo_paths:
                    msg, flood, retry = await self._send_photos_only(
                        tg_id, photo_paths, None, reply_to
                    )
                    if not main_message and msg:
                        main_message = msg
                    if flood:
                        is_flood_wait, retry_after = True, retry

        elif video_data:
            msg, flood, retry = await self._send_videos_only(
                tg_id, video_data, caption_text, reply_to
            )
            if msg:
                main_message = msg
            if flood:
                is_flood_wait, retry_after = True, retry

        elif photo_paths:
            msg, flood, retry = await self._send_photos_only(
                tg_id, photo_paths, caption_text, reply_to
            )
            if msg:
                main_message = msg
            if flood:
                is_flood_wait, retry_after = True, retry

        # Send links to unavailable videos
        if failed_videos and main_message:
            # Build raw text and escape once (no pre-escaping of title).
            links_text = Messages.VIDEO_LINKS_HEADER
            for video in failed_videos:
                video_title = video.get("title", "Видео")
                link = f"https://vk.com/video{video.get('owner_id')}_{video.get('id')}"
                links_text += f"• {video_title}: {link}\n"

            links_text = format_text_for_telegram(links_text)

            reply_to_id = _reply_id(main_message)
            msg, msg_retry = await self.tg.send_message(tg_id, links_text, reply_to=reply_to_id)
            if msg_retry:
                is_flood_wait, retry_after = True, msg_retry

        return (main_message, is_flood_wait, retry_after)

    async def _send_videos_only(
        self,
        tg_id: int,
        video_data: List[Dict],
        caption_text: Optional[str],
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[Message], bool, Optional[int]]:
        """Send only videos"""
        main_message = None
        is_flood_wait = False
        retry_after = None

        for i in range(0, len(video_data), config.config.tg_media_group_limit):
            batch = video_data[i : i + config.config.tg_media_group_limit]
            batch_caption = caption_text if i == 0 else None
            batch_reply = reply_to if i == 0 else None

            msg, msg_retry = await self.tg.send_video_group(
                tg_id, batch, batch_caption, reply_to=batch_reply
            )

            if msg:
                if not main_message:
                    main_message = msg
            elif msg_retry:
                is_flood_wait = True
                retry_after = msg_retry

            if i + config.config.tg_media_group_limit < len(video_data):
                await asyncio.sleep(1)

        return (main_message, is_flood_wait, retry_after)

    async def _send_photos_only(
        self,
        tg_id: int,
        photo_paths: List[str],
        caption_text: Optional[str],
        reply_to: Optional[int] = None,
    ) -> Tuple[Optional[Message], bool, Optional[int]]:
        """Send only photos"""
        if len(photo_paths) == 1:
            msg, msg_retry = await self.tg.send_photo(
                tg_id, photo_paths[0], caption_text, reply_to=reply_to
            )
            if msg:
                logger.debug("photo_sent")
                return (msg, False, None)
            elif msg_retry:
                return (None, True, msg_retry)
        else:
            msg, msg_retry = await self.tg.send_media_group(
                tg_id, photo_paths, caption_text, reply_to=reply_to
            )
            if msg:
                logger.debug("photos_sent", count=len(photo_paths))
                return (msg, False, None)
            elif msg_retry:
                return (None, True, msg_retry)

        return (None, False, None)

    async def _send_media_as_reply(
        self,
        tg_id: int,
        photos: List[Dict],
        videos: List[Dict],
        main_message: Message,
        downloaded_files: List[str],
    ) -> Tuple[bool, bool, Optional[int]]:
        """
        Send photos/videos as a reply to the main message (used by the article strategy).
        Returns: (delivered, is_flood_wait, retry_after)
        """
        if not photos and not videos:
            return (False, False, None)

        reply_to_id = _reply_id(main_message)

        msg, is_flood_wait, retry_after = await self._send_mixed_media(
            tg_id, photos, videos, None, downloaded_files, reply_to=reply_to_id
        )

        return (msg is not None, is_flood_wait, retry_after)

    # =====
    # Send GIFs (animations)
    # Отправка GIF (анимаций)
    # =====

    async def _download_gifs(self, gifs: List[Dict], downloaded_files: List[str]) -> List[str]:
        """Download GIF files, return list of local paths"""
        paths = []
        for gif in gifs:
            url = gif.get("url")
            if not url:
                continue
            path = await self.media.download_document(url, gif.get("title") or "animation", ".gif")
            if path:
                paths.append(path)
                downloaded_files.append(path)
        return paths

    async def _send_gifs(
        self, tg_id: int, gifs: List[Dict], text: str, downloaded_files: List[str]
    ) -> Tuple[Optional[Message], bool, Optional[int]]:
        """
        Send GIF(s) with text as caption in a single message (text + GIF together).
        Extra GIFs and leftover text are sent as replies.
        """
        gif_paths = await self._download_gifs(gifs, downloaded_files)

        if not gif_paths:
            return (None, False, None)

        caption_text, reply_texts = self._smart_split_text(text)

        main_message = None
        is_flood_wait = False
        retry_after = None

        # First GIF carries the caption (GIF + text in one message)
        msg, msg_retry = await self.tg.send_animation(tg_id, gif_paths[0], caption=caption_text)
        if msg:
            main_message = msg
        elif msg_retry:
            is_flood_wait, retry_after = True, msg_retry

        reply_to_id = _reply_id(main_message)

        # Remaining GIFs as reply
        for path in gif_paths[1:]:
            msg, msg_retry = await self.tg.send_animation(tg_id, path, reply_to=reply_to_id)
            if msg_retry:
                is_flood_wait, retry_after = True, msg_retry
            await asyncio.sleep(1)

        # Leftover text as reply
        if main_message and reply_texts:
            flood, retry = await self._send_text_parts_reply(tg_id, reply_texts, main_message)
            if flood:
                is_flood_wait, retry_after = True, retry

        return (main_message, is_flood_wait, retry_after)

    async def _send_gifs_as_reply(
        self, tg_id: int, gifs: List[Dict], reply_to_id: Optional[int], downloaded_files: List[str]
    ) -> Tuple[bool, Optional[int]]:
        """Send GIFs as replies (no caption) - used when there is already a main message"""
        if not gifs:
            return (False, None)

        gif_paths = await self._download_gifs(gifs, downloaded_files)

        is_flood_wait = False
        retry_after = None

        for path in gif_paths:
            msg, msg_retry = await self.tg.send_animation(tg_id, path, reply_to=reply_to_id)
            if msg_retry:
                is_flood_wait, retry_after = True, msg_retry
            await asyncio.sleep(1)

        return (is_flood_wait, retry_after)

    # =====
    # Send text only
    # Отправка только текста
    # =====

    async def _send_text_only(
        self, tg_id: int, text: str
    ) -> Tuple[Optional[Message], bool, Optional[int]]:
        """Send text-only message (up to 4 parts)"""
        _, reply_texts = self._smart_split_text(text, max_caption=4096)

        if not reply_texts:
            reply_texts = [format_text_for_telegram(text)]

        main_message = None
        is_flood_wait = False
        retry_after = None

        for idx, text_part in enumerate(reply_texts[:4]):
            msg, msg_retry = await self.tg.send_message(tg_id, text_part)
            if msg:
                if idx == 0:
                    main_message = msg
            elif msg_retry:
                is_flood_wait = True
                retry_after = msg_retry

            if idx < len(reply_texts) - 1:
                await asyncio.sleep(1)

        return (main_message, is_flood_wait, retry_after)

    # =====
    # Send reply text
    # Отправка текста ответом
    # =====

    async def _send_reply_text(
        self, tg_id: int, reply_text: str, main_message: Message
    ) -> Tuple[bool, Optional[int]]:
        """Send reply text to main message"""
        reply_to_id = _reply_id(main_message)

        _, text_parts = self._smart_split_text(reply_text, max_caption=4096)

        if not text_parts:
            text_parts = [format_text_for_telegram(reply_text)]

        return await self._send_parts(tg_id, text_parts, reply_to_id)

    async def _send_text_parts_reply(
        self, tg_id: int, text_parts: List[str], main_message: Message
    ) -> Tuple[bool, Optional[int]]:
        """Send multiple text parts as reply"""
        reply_to_id = _reply_id(main_message)
        return await self._send_parts(tg_id, text_parts, reply_to_id)

    async def _send_parts(
        self, tg_id: int, text_parts: List[str], reply_to_id: Optional[int]
    ) -> Tuple[bool, Optional[int]]:
        """Send text parts, first one as reply, others as standalone"""
        is_flood_wait = False
        retry_after = None

        for idx, text_part in enumerate(text_parts[:4]):
            result, result_retry = await self.tg.send_message(
                tg_id, text_part, reply_to=reply_to_id if idx == 0 else None
            )
            if result:
                logger.debug("reply_text_sent", part=idx + 1, total=len(text_parts))
            elif result_retry:
                is_flood_wait = True
                retry_after = result_retry

            if idx < len(text_parts) - 1:
                await asyncio.sleep(1)

        return (is_flood_wait, retry_after)

    # =====
    # Send attachments (audio, documents, playlists)
    # Отправка вложений
    # =====

    async def _send_attachments(
        self,
        tg_id: int,
        audios: List[Dict],
        docs: List[Dict],
        audio_playlists: List[Dict],
        main_message: Optional[Message],
        downloaded_files: List[str],
    ) -> Tuple[bool, bool, Optional[int]]:
        """
        Send audio, document and playlist attachments as reply (grouped by type).
        Returns: (delivered, is_flood_wait, retry_after)
        """
        is_flood_wait = False
        retry_after = None
        delivered = False

        reply_to_id = _reply_id(main_message)

        if audio_playlists:
            d, flood, retry = await self._send_audio_playlists(
                tg_id, audio_playlists, reply_to_id, downloaded_files
            )
            delivered = delivered or d
            if flood:
                is_flood_wait, retry_after = True, retry

        if audios:
            d, flood, retry = await self._send_audios_grouped(
                tg_id, audios, reply_to_id, downloaded_files
            )
            delivered = delivered or d
            if flood:
                is_flood_wait, retry_after = True, retry

        if docs:
            d, flood, retry = await self._send_documents_grouped(
                tg_id, docs, reply_to_id, downloaded_files
            )
            delivered = delivered or d
            if flood:
                is_flood_wait, retry_after = True, retry

        return (delivered, is_flood_wait, retry_after)

    async def _send_audio_playlists(
        self,
        tg_id: int,
        playlists: List[Dict],
        reply_to_id: Optional[int],
        downloaded_files: List[str],
    ) -> Tuple[bool, bool, Optional[int]]:
        """Send audio playlists as: cover + title/link"""
        is_flood_wait = False
        retry_after = None
        delivered = False

        for playlist in playlists:
            try:
                playlist_id = playlist.get("id")
                owner_id = playlist.get("owner_id")
                # Title is escaped once here; the text below is sent raw (it contains
                # intentional <b> tags), so it must NOT pass through format_text_for_telegram.
                title = escape_html(playlist.get("title") or Messages.PLAYLIST_DEFAULT_TITLE)
                count = playlist.get("count", 0)
                access_key = playlist.get("access_key", "")

                playlist_url = f"https://vk.com/music/playlist/{owner_id}_{playlist_id}"
                if access_key:
                    playlist_url += f"?access_hash={access_key}"

                photo_url = None
                if "photo" in playlist:
                    photo_data = playlist["photo"]
                    for size in ["photo_600", "photo_300", "photo_135", "photo_68"]:
                        if size in photo_data:
                            photo_url = photo_data[size]
                            break

                playlist_text = Messages.PLAYLIST_INFO.format(
                    title=title, count=count, url=escape_html(playlist_url)
                )

                playlist_message = None

                if photo_url:
                    photo_path = await self.media.download_photo(
                        photo_url, f"playlist_{owner_id}_{playlist_id}.jpg"
                    )
                    if photo_path:
                        downloaded_files.append(photo_path)
                        msg, msg_retry = await self.tg.send_photo(
                            tg_id, photo_path, playlist_text, reply_to=reply_to_id
                        )
                        if msg:
                            playlist_message = msg
                        elif msg_retry:
                            is_flood_wait, retry_after = True, msg_retry

                if not playlist_message:
                    msg, msg_retry = await self.tg.send_message(
                        tg_id, playlist_text, reply_to=reply_to_id
                    )
                    if msg:
                        playlist_message = msg
                    elif msg_retry:
                        is_flood_wait, retry_after = True, msg_retry

                if playlist_message:
                    delivered = True

                logger.debug("playlist_sent", id=playlist_id, title=title, count=count)
                await asyncio.sleep(1)

            except Exception as e:
                logger.error("playlist_send_failed", error=str(e))

        return (delivered, is_flood_wait, retry_after)

    async def _send_audios_grouped(
        self,
        tg_id: int,
        audios: List[Dict],
        reply_to_id: Optional[int],
        downloaded_files: List[str],
    ) -> Tuple[bool, bool, Optional[int]]:
        """
        Send audios as albums (up to 10 per message) so multiple tracks arrive together.
        Audios that fail to download are sent as link messages.
        """
        is_flood_wait = False
        retry_after = None
        delivered = False

        for i in range(0, len(audios), config.config.tg_media_group_limit):
            batch = audios[i : i + config.config.tg_media_group_limit]

            downloaded_batch = []
            failed = []

            for audio in batch:
                audio_url = audio.get("url")
                if not audio_url:
                    failed.append(audio)
                    continue

                audio_path = await self.media.download_audio(
                    audio_url, audio.get("artist", "Unknown"), audio.get("title", "Unknown")
                )

                if audio_path:
                    downloaded_files.append(audio_path)
                    downloaded_batch.append(
                        {
                            "path": audio_path,
                            "title": audio.get("title"),
                            "performer": audio.get("artist"),
                        }
                    )
                else:
                    failed.append(audio)

            # Send the successfully downloaded tracks as one album / Отправляем альбомом
            if downloaded_batch:
                if len(downloaded_batch) == 1:
                    track = downloaded_batch[0]
                    msg, msg_retry = await self.tg.send_audio(
                        tg_id,
                        track["path"],
                        title=track["title"],
                        performer=track["performer"],
                        reply_to=reply_to_id,
                    )
                else:
                    msg, msg_retry = await self.tg.send_audio_group(
                        tg_id, downloaded_batch, reply_to=reply_to_id
                    )

                if msg:
                    delivered = True
                elif msg_retry:
                    is_flood_wait, retry_after = True, msg_retry

            # Send links for the tracks that could not be downloaded
            for audio in failed:
                artist = audio.get("artist", "Unknown")
                title_text = audio.get("title", "Unknown")
                audio_url = audio.get("url")

                if audio_url:
                    message_text = Messages.AUDIO_WITH_LINK.format(
                        artist=artist, title=title_text, url=audio_url
                    )
                else:
                    message_text = Messages.AUDIO_UNAVAILABLE.format(
                        artist=artist, title=title_text
                    )

                message_text = format_text_for_telegram(message_text)
                msg, msg_retry = await self.tg.send_message(
                    tg_id, message_text, reply_to=reply_to_id
                )
                if msg:
                    delivered = True
                elif msg_retry:
                    is_flood_wait, retry_after = True, msg_retry

            if i + config.config.tg_media_group_limit < len(audios):
                await asyncio.sleep(1)

        return (delivered, is_flood_wait, retry_after)

    async def _send_documents_grouped(
        self, tg_id: int, docs: List[Dict], reply_to_id: Optional[int], downloaded_files: List[str]
    ) -> Tuple[bool, bool, Optional[int]]:
        """Send documents (10 per batch)"""
        is_flood_wait = False
        retry_after = None
        delivered = False

        for i in range(0, len(docs), 10):
            batch = docs[i : i + 10]

            for doc in batch:
                try:
                    doc_path = await self.media.download_document(
                        doc.get("url"),
                        doc.get("title"),
                        f".{doc.get('ext', '')}" if doc.get("ext") else "",
                    )

                    if doc_path:
                        downloaded_files.append(doc_path)
                        msg, msg_retry = await self.tg.send_document(
                            tg_id, doc_path, reply_to=reply_to_id
                        )
                        if msg:
                            delivered = True
                        elif msg_retry:
                            is_flood_wait, retry_after = True, msg_retry
                    else:
                        # Raw text, escaped once via format_text_for_telegram (no double escape).
                        doc_type = (doc.get("ext", "Document") or "Document").upper()
                        doc_title = doc.get("title", "Документ")
                        doc_url = doc.get("url", "")
                        message_text = Messages.DOCUMENT_UNAVAILABLE.format(
                            doc_type=doc_type, title=doc_title, url=doc_url
                        )
                        message_text = format_text_for_telegram(message_text)
                        msg, msg_retry = await self.tg.send_message(
                            tg_id, message_text, reply_to=reply_to_id
                        )
                        if msg:
                            delivered = True
                        elif msg_retry:
                            is_flood_wait, retry_after = True, msg_retry

                    await asyncio.sleep(1)

                except Exception as e:
                    logger.error("document_send_failed", error=str(e))

            if i + 10 < len(docs):
                await asyncio.sleep(1)

        return (delivered, is_flood_wait, retry_after)
