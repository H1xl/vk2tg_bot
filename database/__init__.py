"""
Database initialization
Инициализация базы данных
"""

# Configure database logging / Настройка логирования БД
import logging
from datetime import datetime

from tortoise import Tortoise

import config
from utils.logger import logger

if not config.config.show_db_logs:
    # Disable all database logs / Отключение всех логов БД
    logging.getLogger("tortoise").setLevel(logging.CRITICAL)
    logging.getLogger("tortoise.db_client").setLevel(logging.CRITICAL)
    logging.getLogger("aiosqlite").setLevel(logging.CRITICAL)
else:
    # Show database logs / Показывать логи БД
    logging.getLogger("tortoise").setLevel(logging.INFO)
    logging.getLogger("tortoise.db_client").setLevel(logging.INFO)


async def init_database():
    """Initialize database connection"""

    await Tortoise.init(
        db_url=f"sqlite://storage/bot.db", modules={"models": ["database.models"]}, _create_db=True
    )

    await Tortoise.generate_schemas()

    logger.info("database_initialized", db_path="storage/bot.db")


async def close_database():
    """Close database connection"""

    await Tortoise.close_connections()
    logger.info("database_closed")


async def init_permanent_admin():
    """Initialize permanent admin user"""
    from database.models import User

    admin_id = config.config.admin_user_id

    user, created = await User.get_or_create(user_id=admin_id, defaults={"role": "permanent_admin"})

    # Ensure the permanent admin always has the correct role and is never left blocked.
    # Гарантируем правильную роль и снятие блокировки для постоянного админа.
    if not created and (user.role != "permanent_admin" or user.blocked):
        user.role = "permanent_admin"
        user.blocked = False
        user.last_seen = datetime.now()
        await user.save()

    logger.info("permanent_admin_verified", user_id=admin_id)
