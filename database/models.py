"""
Database models with Tortoise ORM
Модели базы данных с Tortoise ORM
"""

from datetime import datetime

from tortoise import fields
from tortoise.models import Model


class Pair(Model):
    """Pair model for VK-Telegram forwarding"""

    id = fields.CharField(pk=True, max_length=50)
    name = fields.CharField(max_length=100, null=True)
    vk_id = fields.IntField(index=True)
    tg_id = fields.BigIntField(index=True)
    is_safe = fields.BooleanField(default=False)
    status = fields.CharField(max_length=20, default="stopped", index=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    # Avatar tracking / Отслеживание аватарки
    avatar_hash = fields.CharField(max_length=64, null=True)
    avatar_updated_at = fields.DatetimeField(null=True)

    class Meta:
        table = "pairs"
        indexes = [
            ("status", "created_at"),
        ]


class PairStats(Model):
    """Statistics for pairs"""

    id = fields.IntField(pk=True)
    pair = fields.OneToOneField("models.Pair", related_name="stats", on_delete=fields.CASCADE)
    last_post_id = fields.IntField(null=True)
    last_update = fields.DatetimeField(auto_now=True)
    posts_24h = fields.IntField(default=0)

    class Meta:
        table = "pair_stats"


class User(Model):
    """User model for authentication"""

    user_id = fields.BigIntField(pk=True)
    username = fields.CharField(max_length=255, null=True)
    role = fields.CharField(max_length=20, default="user", index=True)
    session_expires_at = fields.DatetimeField(null=True)
    blocked = fields.BooleanField(default=False, index=True)
    last_seen = fields.DatetimeField(auto_now=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "users"
        indexes = [
            ("role", "blocked"),
        ]


class InviteCode(Model):
    """Invite code model for temporary admins"""

    id = fields.IntField(pk=True)
    code = fields.CharField(max_length=50, unique=True, index=True)
    created_by = fields.BigIntField()
    created_at = fields.DatetimeField(auto_now_add=True)
    expires_at = fields.DatetimeField()
    used_by = fields.BigIntField(null=True, index=True)
    used_at = fields.DatetimeField(null=True)

    class Meta:
        table = "invite_codes"
        indexes = [
            ("expires_at", "used_by"),
        ]
