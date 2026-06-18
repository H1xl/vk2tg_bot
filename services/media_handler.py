"""
Media Handler with thread-safe cache and single session
Обработчик медиа с потокобезопасным кэшем и единой сессией
"""

import asyncio
import os
import subprocess
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import aiohttp
import yt_dlp

import config
from utils.helpers import format_file_size, sanitize_filename
from utils.logger import logger
from utils.ssl_helper import get_ssl_param

logger = logger.bind(module="media_handler")

# =====
# FFmpeg setup check
# Проверка настройки FFmpeg
# =====


def _setup_ffmpeg_path():
    """Ensure ffmpeg is in PATH"""
    import shutil

    ffmpeg_path = shutil.which("ffmpeg")

    if ffmpeg_path:
        logger.info("ffmpeg_found", path=ffmpeg_path)
        return True

    possible_paths = [
        r"C:\ffmpeg\bin",
        r"C:\Program Files\ffmpeg\bin",
        r"C:\ProgramData\chocolatey\bin",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            ffmpeg_exe = os.path.join(path, "ffmpeg.exe")
            if os.path.exists(ffmpeg_exe):
                os.environ["PATH"] = path + os.pathsep + os.environ.get("PATH", "")
                logger.info("ffmpeg_added_to_path", path=path)
                return True

    logger.error("ffmpeg_not_found")
    return False


_FFMPEG_AVAILABLE = _setup_ffmpeg_path()


class MediaHandler:
    """Handler for downloading and processing media"""

    def __init__(self):
        self.downloads_dir = Path(config.config.downloads_dir)
        self.downloads_dir.mkdir(exist_ok=True)

        self.video_cache = OrderedDict()
        self._video_cache_lock = asyncio.Lock()
        self.VIDEO_CACHE_SIZE = config.config.video_cache_size
        self._last_overflow_log = None

        self._file_references = {}

        self._video_semaphore = asyncio.Semaphore(config.config.max_concurrent_video_downloads)
        self._photo_semaphore = asyncio.Semaphore(config.config.max_concurrent_photo_downloads)
        self._audio_semaphore = asyncio.Semaphore(config.config.max_concurrent_audio_downloads)

        self._session = None
        self._session_lock = asyncio.Lock()

        self.MIN_SPEED_MBPS = 0.5
        self.BASE_TIMEOUT = 30
        self.MAX_TIMEOUT = 1800

    # =====
    # Session management with lazy initialization
    # Управление сессией с отложенной инициализацией
    # =====

    async def _ensure_session(self):
        """Ensure session is initialized (lazy initialization)"""
        if self._session is None or self._session.closed:
            async with self._session_lock:
                if self._session is None or self._session.closed:
                    await self.init_session()

    async def init_session(self):
        """Initialize aiohttp session"""
        if not self._session or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=300, connect=10, sock_read=60)
            self._session = aiohttp.ClientSession(timeout=timeout)
            logger.info("media_handler_session_initialized")

    async def close_session(self):
        """Close aiohttp session"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
            logger.info("media_handler_session_closed")

    # =====
    # Timeout calculation
    # Расчёт таймаута
    # =====

    def _calculate_timeout(self, file_size_bytes: int) -> int:
        """Calculate adaptive timeout based on file size"""
        if file_size_bytes == 0:
            return self.BASE_TIMEOUT

        file_size_mb = file_size_bytes / (1024 * 1024)
        download_time = file_size_mb / self.MIN_SPEED_MBPS
        timeout = int(download_time * 1.5)

        timeout = max(self.BASE_TIMEOUT, min(timeout, self.MAX_TIMEOUT))
        return timeout

    # =====
    # File reference tracking
    # Отслеживание ссылок на файлы
    # =====

    def _add_file_reference(self, filepath: str):
        """Add reference to file"""
        if filepath in self._file_references:
            self._file_references[filepath] += 1
        else:
            self._file_references[filepath] = 1

    def _remove_file_reference(self, filepath: str):
        """Remove reference to file"""
        if filepath in self._file_references:
            self._file_references[filepath] -= 1
            if self._file_references[filepath] <= 0:
                del self._file_references[filepath]

    def _can_delete_file(self, filepath: str) -> bool:
        """Check if file can be safely deleted (no outstanding references)"""
        # Cheap dict lookup - no need to cache (the cache itself never freed entries).
        return self._file_references.get(filepath, 0) == 0

    # =====
    # Thread-safe video cache operations with safe deletion
    # Потокобезопасные операции с кэшем видео с безопасным удалением
    # =====

    async def _update_video_cache(self, key: str, value: dict):
        """Update video cache with size limit and safe file cleanup"""
        async with self._video_cache_lock:
            if len(self.video_cache) >= self.VIDEO_CACHE_SIZE:
                current_time = datetime.now()

                if not self._last_overflow_log or (
                    current_time - self._last_overflow_log
                ) > timedelta(hours=config.config.cache_overflow_cooldown_hours):
                    from utils.logger import log_error

                    await log_error(
                        f"Video cache overflow! Size: {len(self.video_cache)}/{self.VIDEO_CACHE_SIZE}. "
                        f"Consider increasing VIDEO_CACHE_SIZE in config.",
                        is_critical=True,
                    )
                    self._last_overflow_log = current_time

                removed_key, removed_value = self.video_cache.popitem(last=False)
                if "path" in removed_value and removed_value["path"]:
                    filepath = removed_value["path"]
                    can_delete = self._can_delete_file(filepath)

                    if os.path.exists(filepath) and can_delete:
                        try:
                            os.remove(filepath)
                            logger.debug("cache_video_file_removed", path=filepath)
                        except Exception as e:
                            logger.warning("cache_video_removal_failed", error=str(e))
                    elif not can_delete:
                        logger.debug("cache_video_skip_removal_in_use", path=filepath)

            self.video_cache[key] = value

    async def _get_from_video_cache(self, key: str) -> Optional[dict]:
        """Get value from video cache and mark file as in use"""
        async with self._video_cache_lock:
            cached = self.video_cache.get(key)
            if cached and "path" in cached and cached["path"]:
                self._add_file_reference(cached["path"])
            return cached

    # =====
    # Video download
    # Скачивание видео
    # =====

    async def download_vk_video(
        self, owner_id: int, video_id: int, access_key: Optional[str] = None
    ) -> Optional[Dict[str, any]]:
        """
        Download VK video using yt-dlp with timeout
        Returns: dict with 'path', 'width', 'height', 'thumbnail' or None
        """
        async with self._video_semaphore:
            try:
                if not _FFMPEG_AVAILABLE:
                    logger.warning(
                        "video_download_skipped_no_ffmpeg", video=f"{owner_id}_{video_id}"
                    )
                    cache_key = f"{owner_id}_{video_id}"
                    await self._update_video_cache(cache_key, {"unavailable": True})
                    return None

                video_url = f"https://vk.com/video{owner_id}_{video_id}"
                if access_key:
                    video_url += f"?access_key={access_key}"

                cache_key = f"{owner_id}_{video_id}"

                cached = await self._get_from_video_cache(cache_key)
                if cached:
                    if cached.get("unavailable"):
                        logger.info("video_cache_unavailable", video=cache_key)
                        return None
                    if cached.get("path") and os.path.exists(cached.get("path", "")):
                        logger.info("video_cache_hit", video=cache_key)
                        return {
                            "path": cached["path"],
                            "width": cached.get("width"),
                            "height": cached.get("height"),
                            "thumbnail": cached.get("thumbnail"),
                        }

                filename = f"video_{owner_id}_{video_id}"
                filepath = self.downloads_dir / filename
                thumb_path = self.downloads_dir / f"{filename}_thumb.jpg"

                ydl_opts = {
                    "format": "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720][ext=mp4]/best[height<=720]/best",
                    "outtmpl": str(filepath),
                    "merge_output_format": "mp4",
                    "writethumbnail": True,
                    "ignoreerrors": False,
                    "no_warnings": True,
                    "socket_timeout": 30,
                    "retries": 3,
                    "fragment_retries": 3,
                    "concurrent_fragment_downloads": 1,
                    "quiet": True,
                    "no_color": True,
                    "noprogress": True,
                    "logger": self._get_ytdlp_logger(),
                    "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                }

                loop = asyncio.get_event_loop()

                try:
                    info_dict = await asyncio.wait_for(
                        loop.run_in_executor(
                            None, lambda: self._download_with_ytdlp(video_url, ydl_opts)
                        ),
                        timeout=config.config.ytdlp_timeout,
                    )

                    if not info_dict:
                        logger.warning("ytdlp_no_result", video=cache_key)
                        await self._update_video_cache(cache_key, {"unavailable": True})
                        return None

                except asyncio.TimeoutError:
                    logger.error(
                        "ytdlp_timeout", video=cache_key, timeout=config.config.ytdlp_timeout
                    )
                    return None
                except Exception as e:
                    logger.error("ytdlp_exception", video=cache_key, error=str(e))
                    return None

                video_path = self._find_downloaded_file(filepath, cache_key)

                if video_path:
                    file_size = Path(video_path).stat().st_size

                    if file_size > config.config.tg_max_file_size:
                        logger.warning(
                            "video_too_large",
                            size=format_file_size(file_size),
                            max=format_file_size(config.config.tg_max_file_size),
                        )
                        Path(video_path).unlink()
                        await self._update_video_cache(cache_key, {"unavailable": True})
                        return None

                    width = info_dict.get("width")
                    height = info_dict.get("height")

                    thumbnail = None
                    for ext in [".jpg", ".webp", ".png"]:
                        thumb_candidate = Path(str(filepath) + ext)
                        if thumb_candidate.exists():
                            thumbnail = str(thumb_candidate)
                            break

                    logger.info(
                        "video_downloaded",
                        video=cache_key,
                        size=format_file_size(file_size),
                        width=width,
                        height=height,
                        has_thumb=thumbnail is not None,
                    )

                    self._add_file_reference(video_path)
                    if thumbnail:
                        self._add_file_reference(thumbnail)

                    cache_data = {
                        "unavailable": False,
                        "size": file_size,
                        "path": video_path,
                        "width": width,
                        "height": height,
                        "thumbnail": thumbnail,
                    }
                    await self._update_video_cache(cache_key, cache_data)

                    return {
                        "path": video_path,
                        "width": width,
                        "height": height,
                        "thumbnail": thumbnail,
                    }

                logger.warning("video_file_not_found", video=cache_key)
                await self._update_video_cache(cache_key, {"unavailable": True})
                return None

            except Exception as e:
                logger.error("video_download_error", error=str(e), exc_info=True)
                return None

    def _find_downloaded_file(self, filepath: Path, cache_key: str) -> Optional[str]:
        """Find downloaded file with any extension"""
        try:
            filename = filepath.name
            created_files = list(self.downloads_dir.glob(f"{filename}*"))

            if not created_files:
                logger.warning("no_video_files_found", pattern=f"{filename}*")
                return None

            valid_files = [f for f in created_files if f.is_file() and f.stat().st_size > 0]

            if not valid_files:
                logger.warning("no_valid_video_files", cache_key=cache_key)
                return None

            possible_extensions = [".mp4", ".webm", ".mkv", ".flv", ".avi", ".mov", ".m4v"]
            for ext in possible_extensions:
                for file in valid_files:
                    if file.suffix == ext:
                        logger.info(
                            "video_file_selected",
                            file=file.name,
                            size=format_file_size(file.stat().st_size),
                        )
                        return str(file)

            valid_files.sort(key=lambda x: x.stat().st_size, reverse=True)
            selected_file = valid_files[0]

            logger.info(
                "video_file_selected",
                file=selected_file.name,
                size=format_file_size(selected_file.stat().st_size),
            )
            return str(selected_file)

        except Exception as e:
            logger.error("video_file_search_error", error=str(e))
            return None

    def _download_with_ytdlp(self, url: str, opts: dict) -> Optional[dict]:
        """
        Download with yt-dlp (sync)
        Returns: info_dict or None
        """
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info is None:
                    logger.error("ytdlp_no_info", url=url)
                    return None

                if "entries" in info:
                    info = info["entries"][0] if info["entries"] else None

                if info and info.get("requested_downloads"):
                    logger.info("ytdlp_success", url=url)
                    return info

                logger.warning("ytdlp_no_downloads", url=url)
                return None

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            if (
                "Private video" in error_msg
                or "Video unavailable" in error_msg
                or "This video is unavailable" in error_msg
            ):
                logger.warning("ytdlp_video_unavailable", url=url)
            else:
                logger.error("ytdlp_download_error", error=error_msg)
            return None

        except Exception as e:
            logger.error("ytdlp_unexpected_error", error=str(e), exc_info=True)
            return None

    def _get_ytdlp_logger(self):
        """Get custom logger for yt-dlp with suppressed progress"""

        class YTDLPLogger:
            def debug(self, msg):
                if any(x in msg for x in ["[download]", "Downloading", "fragment", "%"]):
                    return
                if msg.startswith("[debug]"):
                    logger.debug("ytdlp", message=msg)

            def info(self, msg):
                if any(
                    x in msg
                    for x in [
                        "[download]",
                        "Downloading",
                        "fragment",
                        "%",
                        "has already been downloaded",
                    ]
                ):
                    return
                logger.debug("ytdlp", message=msg)

            def warning(self, msg):
                logger.warning("ytdlp", message=msg)

            def error(self, msg):
                logger.error("ytdlp", message=msg)

        return YTDLPLogger()

    # =====
    # Photo download
    # Скачивание фото
    # =====

    async def download_photo(self, url: str, filename: str = None) -> Optional[str]:
        """Download photo using single session"""
        async with self._photo_semaphore:
            try:
                await self._ensure_session()

                if not filename:
                    filename = f"photo_{hash(url)}.jpg"

                filepath = self.downloads_dir / filename

                try:
                    async with self._session.head(
                        url, ssl=get_ssl_param(), timeout=aiohttp.ClientTimeout(total=10)
                    ) as response:
                        content_length = int(response.headers.get("Content-Length", 0))
                except Exception as e:
                    logger.debug("photo_size_check_failed", error=str(e))
                    content_length = 0

                timeout_seconds = self._calculate_timeout(content_length)
                timeout = aiohttp.ClientTimeout(total=timeout_seconds, connect=10, sock_read=30)

                async with self._session.get(url, ssl=get_ssl_param(), timeout=timeout) as response:
                    if response.status == 200:
                        content = await response.read()

                        if len(content) > config.config.tg_max_file_size:
                            logger.warning("photo_too_large", size=format_file_size(len(content)))
                            return None

                        with open(filepath, "wb") as f:
                            f.write(content)

                        logger.info("photo_downloaded", size=format_file_size(len(content)))
                        return str(filepath)

                return None

            except asyncio.TimeoutError:
                logger.error("photo_download_timeout")
                return None
            except Exception as e:
                logger.error("photo_download_error", error=str(e))
                return None

    # =====
    # Document download
    # Скачивание документов
    # =====

    async def download_document(
        self, url: str, filename: str = None, extension: str = ""
    ) -> Optional[str]:
        """Download document (audio, gif, doc, etc.)"""
        try:
            await self._ensure_session()

            if not filename:
                filename = f"doc_{hash(url)}{extension}"
            elif extension and not filename.endswith(extension):
                filename = f"{filename}{extension}"

            filename = sanitize_filename(filename)
            filepath = self.downloads_dir / filename

            timeout = aiohttp.ClientTimeout(total=300, connect=10, sock_read=30)

            async with self._session.get(url, ssl=get_ssl_param(), timeout=timeout) as response:
                if response.status == 200:
                    content = await response.read()

                    if len(content) > config.config.tg_max_file_size:
                        logger.warning("document_too_large", size=format_file_size(len(content)))
                        return None

                    with open(filepath, "wb") as f:
                        f.write(content)

                    logger.info("document_downloaded", size=format_file_size(len(content)))
                    return str(filepath)

            return None

        except asyncio.TimeoutError:
            logger.error("document_download_timeout")
            return None
        except Exception as e:
            logger.error("document_download_error", error=str(e))
            return None

    # =====
    # Audio download
    # Скачивание аудио
    # =====

    async def download_audio(
        self, url: str, artist: str = "Unknown", title: str = "Unknown"
    ) -> Optional[str]:
        """Download audio file"""
        async with self._audio_semaphore:
            try:
                safe_artist = sanitize_filename(artist, max_length=50)
                safe_title = sanitize_filename(title, max_length=50)

                if not safe_artist or safe_artist == "unnamed":
                    safe_artist = "Unknown"
                if not safe_title or safe_title == "unnamed":
                    safe_title = "Track"

                filename = f"{safe_artist} - {safe_title}.mp3"

                return await self.download_document(url, filename, ".mp3")

            except Exception as e:
                logger.error("audio_download_error", error=str(e))
                return None

    # =====
    # Cleanup with reference tracking
    # Очистка с отслеживанием ссылок
    # =====

    async def cleanup_file(self, filepath: str):
        """Delete file with reference check"""
        try:
            self._remove_file_reference(filepath)

            can_delete = self._can_delete_file(filepath)

            if can_delete and os.path.exists(filepath):
                os.remove(filepath)
                logger.debug("file_deleted", path=filepath)
        except Exception as e:
            logger.warning("file_cleanup_failed", path=filepath, error=str(e))

    async def cleanup_files(self, filepaths: List[str]):
        """Delete multiple files"""
        for filepath in filepaths:
            await self.cleanup_file(filepath)

    async def cleanup_pair_files(self, pair_id: str, vk_id: int):
        """Clean all files related to pair"""
        try:
            count = 0
            for pattern in [f"*vk_{vk_id}*", f"*{vk_id}_*", f"*video_{vk_id}*"]:
                for file_path in self.downloads_dir.glob(pattern):
                    file_str = str(file_path)
                    can_delete = self._can_delete_file(file_str)

                    if file_path.is_file() and can_delete:
                        try:
                            file_path.unlink()
                            count += 1
                        except Exception as e:
                            logger.warning("pair_file_cleanup_failed", file=file_str, error=str(e))

            if count > 0:
                logger.info("pair_files_cleaned", pair_id=pair_id, count=count)

        except Exception as e:
            logger.error("pair_cleanup_error", pair_id=pair_id, error=str(e))
