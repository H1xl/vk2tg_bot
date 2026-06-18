"""
Database migration script
Скрипт миграции базы данных
"""

import asyncio
import os
import sys

# Add parent directory to path / Добавить родительскую директорию в path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from tortoise import Tortoise

import config


async def migrate():
    """Run database migration to add avatar fields"""

    print("Starting database migration...")

    # Initialize Tortoise ORM
    await Tortoise.init(
        db_url=f"sqlite://{config.config.storage_dir}/bot.db",
        modules={"models": ["database.models"]},
    )

    # Get connection
    conn = Tortoise.get_connection("default")

    try:
        # Check if columns already exist
        result = await conn.execute_query("PRAGMA table_info(pairs)")

        existing_columns = [row[1] for row in result[1]]

        # Add avatar_hash column if not exists
        if "avatar_hash" not in existing_columns:
            print("Adding avatar_hash column...")
            await conn.execute_query("ALTER TABLE pairs ADD COLUMN avatar_hash VARCHAR(64)")
            print("✓ avatar_hash column added")
        else:
            print("✓ avatar_hash column already exists")

        # Add avatar_updated_at column if not exists
        if "avatar_updated_at" not in existing_columns:
            print("Adding avatar_updated_at column...")
            await conn.execute_query("ALTER TABLE pairs ADD COLUMN avatar_updated_at TIMESTAMP")
            print("✓ avatar_updated_at column added")
        else:
            print("✓ avatar_updated_at column already exists")

        print("\n✅ Migration completed successfully!")
        print("\n⚠️  Please restart the bot for changes to take effect.")

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        sys.exit(1)

    finally:
        await Tortoise.close_connections()


if __name__ == "__main__":
    try:
        asyncio.run(migrate())
    except KeyboardInterrupt:
        print("\n⚠️  Migration cancelled by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)
