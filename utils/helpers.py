"""
Helper utilities
Вспомогательные утилиты
"""

import hashlib
import html
import json
import os
import re
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, List, Optional, Tuple

import aiofiles

import config

# =====
# Atomic file write with backup
# Атомарная запись в файл с резервной копией
# =====


async def atomic_write(filepath: str, data: Any):
    """Write data to file atomically with backup"""

    temp_filepath = f"{filepath}.tmp"

    try:
        if os.path.exists(filepath):
            await create_backup(filepath)

        async with aiofiles.open(temp_filepath, "w", encoding="utf-8") as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=2))

        os.replace(temp_filepath, filepath)
    except Exception as e:
        if os.path.exists(temp_filepath):
            os.remove(temp_filepath)
        raise e


async def create_backup(filepath: str):
    """Create backup of file"""

    try:
        backup_dir = Path(filepath).parent / "backups"
        backup_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = Path(filepath).name
        backup_path = backup_dir / f"{filename}.{timestamp}.bak"

        shutil.copy2(filepath, backup_path)

        await cleanup_old_backups(backup_dir, filename, config.config.storage_backup_count)

    except Exception as e:
        from utils.logger import logger

        logger.warning("backup_failed", error=str(e))


async def cleanup_old_backups(backup_dir: Path, filename: str, keep_count: int):
    """Remove old backup files"""

    try:
        backups = sorted(
            backup_dir.glob(f"{filename}.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True
        )

        for backup in backups[keep_count:]:
            backup.unlink()

    except Exception as e:
        from utils.logger import logger

        logger.warning("backup_cleanup_failed", error=str(e))


# =====
# Read JSON file with validation
# Чтение JSON файла с валидацией
# =====


async def read_json(filepath: str, default: Any = None) -> Any:
    """Read JSON file with validation"""

    from utils.logger import log_error, logger

    if not os.path.exists(filepath):
        return default if default is not None else {}

    try:
        async with aiofiles.open(filepath, "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)

            if not isinstance(data, (dict, list)):
                raise ValueError("Invalid JSON structure: must be dict or list")

            return data

    except json.JSONDecodeError as e:
        await log_error(f"JSON decode error in {filepath}: {e}", is_critical=True)

        restored = await restore_from_backup(filepath)
        if restored:
            logger.info("backup_restored", file=filepath)
            return restored

        logger.error("backup_restore_failed", file=filepath)
        return default if default is not None else {}

    except Exception as e:
        await log_error(f"Error reading {filepath}: {e}", is_critical=True)
        return default if default is not None else {}


async def restore_from_backup(filepath: str) -> Any:
    """Restore file from most recent backup"""

    try:
        backup_dir = Path(filepath).parent / "backups"
        filename = Path(filepath).name

        if not backup_dir.exists():
            return None

        backups = sorted(
            backup_dir.glob(f"{filename}.*.bak"), key=lambda x: x.stat().st_mtime, reverse=True
        )

        if not backups:
            return None

        async with aiofiles.open(backups[0], "r", encoding="utf-8") as f:
            content = await f.read()
            data = json.loads(content)

        shutil.copy2(backups[0], filepath)

        return data

    except Exception as e:
        from utils.logger import logger

        logger.error("backup_restore_error", error=str(e))
        return None


# =====
# Image hashing for comparison
# Хеширование изображений для сравнения
# =====


async def calculate_image_hash(filepath: str) -> Optional[str]:
    """
    Calculate SHA256 hash of image file
    Returns hex digest for comparison
    """

    try:
        if not os.path.exists(filepath):
            return None

        sha256_hash = hashlib.sha256()

        async with aiofiles.open(filepath, "rb") as f:
            while chunk := await f.read(8192):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()

    except Exception as e:
        from utils.logger import logger

        logger.error("image_hash_failed", filepath=filepath, error=str(e))
        return None


def calculate_image_hash_sync(filepath: str) -> Optional[str]:
    """
    Calculate SHA256 hash of image file (synchronous version)
    Returns hex digest for comparison
    """

    try:
        if not os.path.exists(filepath):
            return None

        sha256_hash = hashlib.sha256()

        with open(filepath, "rb") as f:
            while chunk := f.read(8192):
                sha256_hash.update(chunk)

        return sha256_hash.hexdigest()

    except Exception as e:
        from utils.logger import logger

        logger.error("image_hash_failed", filepath=filepath, error=str(e))
        return None


# =====
# HTML formatting for Telegram
# HTML форматирование для Telegram
# =====


def format_text_for_telegram(text: str) -> str:
    """
    Format text for HTML parse_mode
    Escapes special characters and preserves allowed tags
    """

    if not text:
        return ""

    # Escape HTML special characters / Экранирование спецсимволов HTML
    text = html.escape(text)

    # Convert markdown-like formatting to HTML / Конвертация markdown в HTML
    # **bold** → <b>bold</b>
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)

    # *italic* → <i>italic</i>
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)

    # `code` → <code>code</code>
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)

    # [text](url) → <a href="url">text</a>
    text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)

    return text


def escape_html(text: Any) -> str:
    """Simple HTML escaping without formatting. Coerces non-strings (e.g. int ids)."""

    if not text:
        return ""
    return html.escape(text if isinstance(text, str) else str(text))


# =====
# Text splitting
# Разбиение текста
# =====


def split_long_text(text: str, max_length: int = 4096) -> list:
    """Split long text into multiple messages"""

    if len(text) <= max_length:
        return [text]

    messages = []
    current_message = ""

    # Split by paragraphs first / Сначала по параграфам
    paragraphs = text.split("\n\n")

    for paragraph in paragraphs:
        # If single paragraph is too long, split by sentences
        if len(paragraph) > max_length:
            sentences = paragraph.split(". ")
            for sentence in sentences:
                if len(current_message) + len(sentence) + 2 <= max_length:
                    current_message += sentence + ". "
                else:
                    if current_message:
                        messages.append(current_message.strip())
                    current_message = sentence + ". "
        else:
            if len(current_message) + len(paragraph) + 2 <= max_length:
                current_message += paragraph + "\n\n"
            else:
                if current_message:
                    messages.append(current_message.strip())
                current_message = paragraph + "\n\n"

    if current_message:
        messages.append(current_message.strip())

    return messages


# =====
# Progress bar formatting
# Форматирование прогресс-бара
# =====


def pad_cell(text: Any, width: int) -> str:
    """
    Build a fixed-width, HTML-escaped table cell for use inside a <pre> block.
    Truncates with an ellipsis if too long; pads with spaces on the right.
    Width is computed on the raw text, then the value is escaped (entities still
    render as single characters inside <pre>, so visual alignment is preserved).
    Ячейка фиксированной ширины для таблицы внутри <pre> (с обрезкой и экранированием).
    """
    text = str(text) if text is not None else ""
    if len(text) > width:
        text = text[: width - 1] + "…" if width > 0 else ""
    return escape_html(text.ljust(width))


def format_progress_bar(current: int, total: int, length: int = 20) -> str:
    """
    Format progress bar for visual progress indication
    Returns: [████████████░░░░░░░░] 40%
    """

    if total <= 0:
        percent = 0
        filled = 0
    else:
        # Clamp so current > total never overflows the bar / Ограничиваем, чтобы не выйти за пределы
        ratio = min(1.0, max(0.0, current / total))
        percent = int(ratio * 100)
        filled = int(ratio * length)

    bar = "█" * filled + "░" * (length - filled)

    return f"[{bar}] {percent}%"


# =====
# Cleanup temporary files
# Очистка временных файлов
# =====


async def cleanup_temp_files(max_age_seconds: int = None):
    """Clean up old temporary files"""

    if max_age_seconds is None:
        max_age_seconds = config.config.temp_file_max_age

    try:
        downloads_path = Path(config.config.downloads_dir)
        if not downloads_path.exists():
            return

        count = 0
        current_time = datetime.now()
        cutoff_time = current_time - timedelta(seconds=max_age_seconds)

        for file_path in downloads_path.iterdir():
            if file_path.is_file():
                try:
                    file_mtime = datetime.fromtimestamp(file_path.stat().st_mtime)

                    if file_mtime < cutoff_time:
                        file_path.unlink()
                        count += 1
                except Exception:
                    pass

        if count > 0:
            from utils.logger import logger

            logger.info("temp_files_cleaned", count=count, max_age_seconds=max_age_seconds)
    except Exception as e:
        from utils.logger import logger

        logger.warning("temp_cleanup_failed", error=str(e))


async def cleanup_all_temp_files():
    """Clean up ALL temporary files on startup"""

    try:
        downloads_path = Path(config.config.downloads_dir)
        if not downloads_path.exists():
            return

        count = 0
        for file_path in downloads_path.iterdir():
            if file_path.is_file():
                try:
                    file_path.unlink()
                    count += 1
                except Exception:
                    pass

        if count > 0:
            from utils.logger import logger

            logger.info("startup_cleanup_complete", count=count)
    except Exception as e:
        from utils.logger import logger

        logger.warning("startup_cleanup_failed", error=str(e))


# =====
# Generate next pair ID with UUID fallback
# Генерация следующего ID пары с UUID fallback
# =====


def generate_next_pair_id(existing_ids: list) -> str:
    """
    Generate next available pair ID
    Uses sequential numbering with UUID fallback for race conditions
    """

    if not existing_ids:
        return "pair1"

    numbers = []
    for pair_id in existing_ids:
        match = re.match(r"pair(\d+)", pair_id)
        if match:
            numbers.append(int(match.group(1)))

    if not numbers:
        return "pair1"

    next_num = max(numbers) + 1
    return f"pair{next_num}"


def generate_unique_pair_id() -> str:
    """
    Generate unique pair ID using UUID
    Used as fallback when sequential ID conflicts
    """
    return f"pair_{uuid.uuid4().hex[:8]}"


# =====
# Format file size
# Форматирование размера файла
# =====


def format_file_size(size_bytes: int) -> str:
    """Format file size in human readable format"""

    for unit in ["B", "KB", "MB", "GB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"


"""
Helper utilities - Smart text splitting addition
Вспомогательные утилиты - Дополнение умного деления текста
"""


def smart_split_text_for_caption(
    text: str, max_caption: int = 1024
) -> Tuple[Optional[str], List[str]]:
    """
    Smart text splitting: maximum in caption, rest in reply messages
    Splits by paragraphs to preserve readability

    Args:
        text: Text to split
        max_caption: Maximum caption length (default 1024)

    Returns:
        Tuple of (caption_text, list_of_reply_texts)
        - caption_text: Text for caption (or None if empty)
        - list_of_reply_texts: List of texts for reply messages (up to 4)

    Examples:
        # Short text
        >>> smart_split_text_for_caption("Hello")
        ("Hello", [])

        # Text fits in caption
        >>> text = "Paragraph 1\\n\\nParagraph 2"  # total < 1024
        >>> smart_split_text_for_caption(text)
        ("Paragraph 1\\n\\nParagraph 2", [])

        # Text needs splitting
        >>> text = "Para1 (900 chars)\\n\\nPara2 (500 chars)"  # total > 1024
        >>> smart_split_text_for_caption(text)
        ("Para1 (900 chars)", ["Para2 (500 chars)"])
    """
    if not text:
        return (None, [])

    # Если текст влезает целиком - возвращаем как caption
    if len(text) <= max_caption:
        return (format_text_for_telegram(text), [])

    # Делим на абзацы
    paragraphs = text.split("\n\n")
    caption_parts = []
    remaining_parts = []
    current_caption_length = 0
    caption_filled = False

    for para in paragraphs:
        para_length = len(para)

        # Если caption ещё не заполнен
        if not caption_filled:
            # Проверяем влезет ли абзац целиком (с учётом \n\n)
            additional_length = para_length + (2 if caption_parts else 0)

            if current_caption_length + additional_length <= max_caption:
                caption_parts.append(para)
                current_caption_length += additional_length
            else:
                # Caption заполнен, остаток идёт в reply
                caption_filled = True
                remaining_parts.append(para)
        else:
            # Caption уже заполнен, всё в remaining
            remaining_parts.append(para)

    # Формируем caption
    caption_text = None
    if caption_parts:
        caption_text = format_text_for_telegram("\n\n".join(caption_parts))

    # Формируем reply сообщения (до 4 штук по 4096 символов)
    if not remaining_parts:
        return (caption_text, [])

    reply_messages = []
    current_reply = []
    current_reply_length = 0

    for para in remaining_parts:
        para_length = len(para)
        additional_length = para_length + (2 if current_reply else 0)

        # Если абзац влезает в текущее сообщение
        if current_reply_length + additional_length <= 4096:
            current_reply.append(para)
            current_reply_length += additional_length
        else:
            # Сохраняем текущее сообщение и начинаем новое
            if current_reply:
                reply_messages.append(format_text_for_telegram("\n\n".join(current_reply)))

            # Если один абзац > 4096, разбиваем его по предложениям
            if para_length > 4096:
                split_paragraphs = _split_long_paragraph(para)
                for split_para in split_paragraphs:
                    if len(reply_messages) < 4:
                        reply_messages.append(format_text_for_telegram(split_para))
                current_reply = []
                current_reply_length = 0
            else:
                current_reply = [para]
                current_reply_length = para_length

        # Ограничение: максимум 4 reply сообщения
        if len(reply_messages) >= 4:
            break

    # Добавляем последнее сообщение
    if current_reply and len(reply_messages) < 4:
        reply_messages.append(format_text_for_telegram("\n\n".join(current_reply)))

    return (caption_text, reply_messages[:4])


def _split_long_paragraph(paragraph: str, max_length: int = 4096) -> List[str]:
    """
    Split a single long paragraph into multiple parts
    Splits by sentences to preserve readability

    Args:
        paragraph: Long paragraph to split
        max_length: Maximum length per part

    Returns:
        List of paragraph parts
    """
    if len(paragraph) <= max_length:
        return [paragraph]

    # Пробуем разбить по предложениям
    sentences = paragraph.split(". ")
    parts = []
    current_part = ""

    for sentence in sentences:
        sentence_with_dot = sentence if sentence.endswith(".") else sentence + ". "

        if len(current_part) + len(sentence_with_dot) <= max_length:
            current_part += sentence_with_dot
        else:
            if current_part:
                parts.append(current_part.strip())
            current_part = sentence_with_dot

    if current_part:
        parts.append(current_part.strip())

    # Если предложения слишком длинные, режем по max_length
    final_parts = []
    for part in parts:
        if len(part) <= max_length:
            final_parts.append(part)
        else:
            # Грубое разбиение по max_length
            for i in range(0, len(part), max_length):
                final_parts.append(part[i : i + max_length])

    return final_parts


# =====
# Sanitize filename with path traversal protection
# Очистка имени файла с защитой от path traversal
# =====


def sanitize_filename(filename: str, max_length: int = 100) -> str:
    """
    Sanitize filename for safe filesystem usage
    Protects against path traversal attacks
    """

    if not filename:
        return "unnamed"

    # Strip any directory component, then remove characters illegal on common
    # filesystems (this also removes path separators, so no traversal is possible).
    # Отбрасываем путь и удаляем недопустимые символы (заодно убираются разделители путей).
    filename = os.path.basename(filename)
    invalid_chars = r'[/\\:*?"<>|]'
    sanitized = re.sub(invalid_chars, "_", filename).strip(" .")

    if not sanitized or sanitized in (".", ".."):
        sanitized = "unnamed"

    # Avoid Windows reserved device names (CON, NUL, COM1, ...) / Зарезервированные имена Windows
    reserved = {
        "con",
        "prn",
        "aux",
        "nul",
        *(f"com{i}" for i in range(1, 10)),
        *(f"lpt{i}" for i in range(1, 10)),
    }
    if sanitized.split(".", 1)[0].lower() in reserved:
        sanitized = f"_{sanitized}"

    # Truncate to max length while preserving extension
    # Обрезка до максимальной длины с сохранением расширения
    if len(sanitized) > max_length:
        parts = sanitized.rsplit(".", 1)
        if len(parts) == 2:
            name, ext = parts
            max_name_length = max_length - len(ext) - 1
            sanitized = f"{name[:max_name_length]}.{ext}"
        else:
            sanitized = sanitized[:max_length]

    return sanitized
