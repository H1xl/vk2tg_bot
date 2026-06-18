"""
Database initialization
Инициализация базы данных
"""

from tortoise import Tortoise

import config
from utils.logger import logger

# =====
# Database initialization
# Инициализация базы данных
# =====


async def init_database():
    """Initialize Tortoise ORM and create tables"""

    await Tortoise.init(
        db_url=f"sqlite://{config.config.storage_dir}/bot.db",
        modules={"models": ["database.models"]},
    )

    # Create tables if not exist / Создание таблиц если не существуют
    await Tortoise.generate_schemas()

    logger.info("database_initialized", db_path=f"{config.config.storage_dir}/bot.db")


async def close_database():
    """Close database connections"""

    await Tortoise.close_connections()
    logger.info("database_closed")


# =====
# Permanent admin initialization
# Инициализация постоянного администратора
# =====


async def init_permanent_admin():
    """Create or verify permanent admin in database"""

    from database.models import User

    admin_id = config.config.admin_user_id

    # Check if admin exists / Проверяем существование админа
    admin = await User.get_or_none(user_id=admin_id)

    if not admin:
        admin = await User.create(user_id=admin_id, role="permanent_admin", blocked=False)
        logger.info("permanent_admin_created", user_id=admin_id)
    else:
        # Update role to ensure it's correct / Обновляем роль
        admin.role = "permanent_admin"
        admin.blocked = False
        await admin.save()
        logger.info("permanent_admin_verified", user_id=admin_id)
