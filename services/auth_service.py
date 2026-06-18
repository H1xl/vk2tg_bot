"""
Authentication Service
Сервис аутентификации
"""

import secrets
import string
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from tortoise.exceptions import DoesNotExist

import config
from database.models import InviteCode, User
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="auth_service")


class AuthService:
    """Service for authentication and role management"""

    def __init__(self, bot):
        self.bot = bot

    # =====
    # Helper for timezone-aware datetime
    # Помощник для datetime с timezone
    # =====

    @staticmethod
    def _now():
        """Get current timezone-aware datetime"""
        return datetime.now(timezone.utc)

    # =====
    # User access check
    # Проверка доступа пользователя
    # =====

    async def check_user_access(
        self, user_id: int, username: Optional[str] = None
    ) -> Tuple[str, bool]:
        """
        Check user role and block status. Captures/updates the Telegram @username
        when provided, so it can later be shown instead of the raw numeric id.
        Returns: (role, is_blocked)
        """

        # Permanent admin is never blocked / Постоянный админ никогда не блокируется
        if user_id == config.config.admin_user_id:
            return ("permanent_admin", False)

        try:
            user = await User.get(user_id=user_id)
        except DoesNotExist:
            # New user - create with default role / Новый пользователь
            user = await User.create(user_id=user_id, role="user", username=username)
            logger.info("new_user_created", user_id=user_id)
            return ("user", False)

        # Update last_seen and username (if it changed) / Обновляем last_seen и username
        if username and user.username != username:
            user.username = username
        user.last_seen = self._now()
        await user.save()

        # Check temp_admin session expiry / Проверяем истечение сессии temp_admin
        if user.role == "temp_admin" and user.session_expires_at:
            if self._now() > user.session_expires_at:
                # Session expired / Сессия истекла
                user.role = "user"
                await user.save()

                # Notify user + reset their menu/keyboard / Уведомляем и сбрасываем меню
                await self._reset_role_ui(user_id, Messages.SESSION_EXPIRED)

                logger.info("temp_admin_session_expired", user_id=user_id)
                return ("user", user.blocked)

        return (user.role, user.blocked)

    async def _reset_role_ui(self, user_id: int, text: str):
        """
        On losing admin rights: revert the native command menu to the public set
        and push a fresh user-level reply keyboard, so the user does not keep stale
        admin buttons/commands until they re-open the chat.
        При потере прав: сбрасываем нативное меню к публичному и обновляем reply-клавиатуру.
        """
        from utils import keyboards as kb

        try:
            from handlers.menu import reset_commands_for_chat

            await reset_commands_for_chat(self.bot, user_id)
        except Exception as e:
            logger.warning("role_ui_commands_reset_failed", user_id=user_id, error=str(e))

        try:
            await self.bot.send_message(
                user_id,
                text,
                parse_mode="HTML",
                reply_markup=kb.menu_keyboard_for_role("user"),
            )
        except Exception as e:
            logger.warning("role_ui_keyboard_reset_failed", user_id=user_id, error=str(e))

    async def get_user_mention(self, user_id: int) -> str:
        """
        Build a display mention for a user: '@username' if we have it stored,
        otherwise the numeric id in <code>. (Bot API can't resolve an arbitrary
        id to a username, so this relies on a previously captured username.)
        Возвращает @username (если сохранён) либо ID в <code>.
        """
        if user_id == config.config.admin_user_id:
            return f"<code>{user_id}</code>"
        try:
            user = await User.get(user_id=user_id)
            if user.username:
                return f"@{user.username}"
        except DoesNotExist:
            pass
        return f"<code>{user_id}</code>"

    # =====
    # Invite code management
    # Управление кодами приглашения
    # =====

    async def generate_invite_code(self, admin_id: int) -> str:
        """Generate invite code for temporary admin"""

        # Format: ADMIN-XXXX-XXXX
        chars = string.ascii_uppercase + string.digits
        code_part1 = "".join(secrets.choice(chars) for _ in range(4))
        code_part2 = "".join(secrets.choice(chars) for _ in range(4))
        code = f"ADMIN-{code_part1}-{code_part2}"

        # Save to database / Сохраняем в БД
        expires_at = self._now() + timedelta(hours=24)

        await InviteCode.create(code=code, created_by=admin_id, expires_at=expires_at)

        logger.info("invite_code_generated", admin_id=admin_id, code=code)

        return code

    async def use_invite_code(
        self, code: str, user_id: int, username: Optional[str] = None
    ) -> bool:
        """
        Use invite code
        Returns: True if successful, False if invalid
        """

        try:
            invite = await InviteCode.get(code=code)
        except DoesNotExist:
            logger.warning("invite_code_not_found", code=code, user_id=user_id)
            return False

        # Validation checks / Проверки
        if invite.used_by is not None:
            logger.warning("invite_code_already_used", code=code, user_id=user_id)
            return False

        if self._now() > invite.expires_at:
            logger.warning("invite_code_expired", code=code, user_id=user_id)
            return False

        # Use code / Используем код
        invite.used_by = user_id
        invite.used_at = self._now()
        await invite.save()

        # Update user / Обновляем пользователя
        user, created = await User.get_or_create(user_id=user_id, defaults={"role": "user"})

        user.role = "temp_admin"
        user.session_expires_at = self._now() + timedelta(hours=24)
        # Capture the latest @username so the notification can show a clickable mention
        # Сохраняем актуальный @username для кликабельного упоминания в уведомлении
        if username:
            user.username = username
        await user.save()

        # Notify permanent admin / Уведомляем постоянного админа
        try:
            uname = username or user.username
            if uname:
                user_mention = f'<a href="tg://user?id={user_id}">@{uname}</a>'
            else:
                user_mention = f"<code>{user_id}</code>"
            expires_str = user.session_expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")

            await self.bot.send_message(
                config.config.error_channel_id,
                Messages.TEMP_ADMIN_NOTIFICATION.format(
                    user_mention=user_mention, user_id=user_id, code=code, expires_str=expires_str
                ),
                parse_mode="HTML",
            )
        except Exception as e:
            logger.error("temp_admin_notification_failed", error=str(e))

        logger.info("invite_code_used", code=code, user_id=user_id, created_by=invite.created_by)

        return True

    # =====
    # Admin management
    # Управление администраторами
    # =====

    async def revoke_temp_admin(self, user_id: int) -> bool:
        """Revoke temporary admin rights"""

        try:
            user = await User.get(user_id=user_id)
        except DoesNotExist:
            return False

        if user.role != "temp_admin":
            return False

        user.role = "user"
        user.session_expires_at = None
        await user.save()

        # Notify user + reset their menu/keyboard / Уведомляем и сбрасываем меню
        await self._reset_role_ui(user_id, Messages.TEMP_ADMIN_REVOKED)

        logger.info("temp_admin_revoked", user_id=user_id)

        return True

    # =====
    # User blocking
    # Блокировка пользователей
    # =====

    async def block_user(self, user_id: int) -> bool:
        """Block user (for reports only)"""

        # CRITICAL: cannot block permanent admin / КРИТИЧНО: нельзя блокировать постоянного админа
        if user_id == config.config.admin_user_id:
            logger.warning("block_permanent_admin_attempt", user_id=user_id)
            return False

        try:
            user = await User.get(user_id=user_id)
        except DoesNotExist:
            # Create blocked user / Создаём заблокированного пользователя
            await User.create(user_id=user_id, role="user", blocked=True)
            logger.info("user_blocked_created", user_id=user_id)
            return True

        user.blocked = True
        await user.save()

        logger.info("user_blocked", user_id=user_id)
        return True

    async def unblock_user(self, user_id: int) -> bool:
        """Unblock user"""

        try:
            user = await User.get(user_id=user_id)
            user.blocked = False
            await user.save()

            logger.info("user_unblocked", user_id=user_id)
            return True
        except DoesNotExist:
            return False

    async def get_blocked_users(self) -> List[User]:
        """Get list of blocked users"""

        return await User.filter(blocked=True).all()
