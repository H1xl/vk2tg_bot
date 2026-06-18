"""
Validators module with Pydantic
Модуль валидации с Pydantic
"""

import re
from typing import Optional

from pydantic import BaseModel, Field, field_validator

# =====
# VK ID Validation
# Валидация VK ID
# =====


def validate_vk_id(vk_input: str) -> Optional[str]:
    """
    Validate VK ID or extract a group identifier from many link forms.

    Accepts (case-insensitive), with or without scheme/host/query/fragment:
      - 123 / -123                     -> "123"
      - apiclub / durov                -> "apiclub"
      - vk.com/apiclub                 -> "apiclub"
      - https://vk.com/apiclub         -> "apiclub"
      - http://www.vk.com/apiclub/     -> "apiclub"
      - https://m.vk.ru/club123        -> "123"
      - vk.com/public123 / event123    -> "123"
      - vk.com/wall-123_456            -> "123"
      - https://vk.com/feed?w=wall-123_456 -> "123"

    Returns a numeric group id or a screen_name (or None if nothing parsed).
    """

    if not vk_input:
        return None

    vk_input = vk_input.strip()

    # 1) Plain numeric id (optionally negative for group owner ids) / Числовой ID
    if re.fullmatch(r"-?\d+", vk_input):
        return vk_input.lstrip("-")

    # 2) Wall link in path or query: wall-123_456 / wall123_456 -> group id
    #    Ссылка на стену -> id владельца (группы)
    match = re.search(r"wall(-?\d+)_\d+", vk_input, re.IGNORECASE)
    if match:
        return match.group(1).lstrip("-")

    # 3) Numeric group forms: club123 / public123 / event123 -> "123"
    match = re.search(r"(?:club|public|event)(\d+)", vk_input, re.IGNORECASE)
    if match:
        return match.group(1)

    # 4) Screen name inside a vk.com / vk.ru URL (ignores query/fragment/trailing path)
    #    Имя со страницы vk.com/vk.ru (аргументы и хвост пути отбрасываются)
    match = re.search(r"vk\.(?:com|ru)/([a-zA-Z0-9_]+)", vk_input, re.IGNORECASE)
    if match:
        return match.group(1)

    # 5) Bare screen_name / Просто screen_name
    if re.fullmatch(r"[a-zA-Z0-9_]+", vk_input):
        return vk_input

    return None


# =====
# Telegram ID Validation
# Валидация Telegram ID
# =====


def validate_tg_id(tg_input: str) -> Optional[int]:
    """
    Validate Telegram ID or extract from link
    Returns numeric ID or username
    """

    tg_input = tg_input.strip()

    # Direct numeric ID / Прямой числовой ID
    if tg_input.lstrip("-").isdigit():
        return int(tg_input)

    # Username format / Формат username
    if tg_input.startswith("@"):
        return tg_input

    # Extract from Telegram link / Извлечение из ссылки Telegram
    patterns = [
        r"t\.me/([a-zA-Z0-9_]+)",
        r"telegram\.me/([a-zA-Z0-9_]+)",
    ]

    for pattern in patterns:
        match = re.search(pattern, tg_input)
        if match:
            return f"@{match.group(1)}"

    return None


# =====
# Pair Name Validation
# Валидация имени пары
# =====


def validate_pair_name(name: str) -> bool:
    """Validate pair name length"""

    if not name:
        return True
    return len(name) <= 100


# =====
# Pair ID Validation
# Валидация ID пары
# =====


def validate_pair_id(pair_id: str) -> bool:
    """Validate pair ID format"""

    if not pair_id:
        return False

    # Remove quotes if present / Удалить кавычки
    pair_id = pair_id.strip("\"'")

    return bool(re.match(r"^[a-zA-Z0-9_]+$", pair_id)) and len(pair_id) <= 50


# =====
# Boolean Validation
# Валидация булевого значения
# =====


def validate_is_safe(value: str) -> Optional[bool]:
    """Validate is_safe parameter"""

    if not value:
        return False

    value = value.lower().strip()

    if value in ["true", "1", "yes"]:
        return True
    elif value in ["false", "0", "no"]:
        return False

    return None


# =====
# Pydantic Models for validation
# Pydantic модели для валидации
# =====


class PairCreateModel(BaseModel):
    """Validation model for pair creation"""

    vk_id: int = Field(..., gt=0)
    tg_id: int
    name: Optional[str] = Field(None, max_length=100)
    is_safe: bool = Field(False)
    pair_id: Optional[str] = Field(None, max_length=50)

    @field_validator("pair_id")
    @classmethod
    def validate_pair_id_format(cls, v: Optional[str]) -> Optional[str]:
        """Validate pair_id format"""
        if v is None:
            return v

        if not re.match(r"^[a-zA-Z0-9_]+$", v):
            raise ValueError("pair_id must contain only letters, numbers and underscores")

        return v


class InviteCodeModel(BaseModel):
    """Validation model for invite code"""

    code: str = Field(..., min_length=8, max_length=50)

    @field_validator("code")
    @classmethod
    def validate_code_format(cls, v: str) -> str:
        """Validate invite code format"""
        if not re.match(r"^ADMIN-[A-Z0-9]{4}-[A-Z0-9]{4}$", v):
            raise ValueError("Invalid invite code format")

        return v


class ReportModel(BaseModel):
    """Validation model for user report"""

    reason: str = Field(..., min_length=10, max_length=500)
    channel_id: int
    message_id: int
    user_id: int

    @field_validator("reason")
    @classmethod
    def validate_reason_content(cls, v: str) -> str:
        """Validate report reason content"""
        v = v.strip()

        if len(v) < 10:
            raise ValueError("Reason must be at least 10 characters")

        return v
