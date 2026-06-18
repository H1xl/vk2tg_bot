"""
Main entry point
Главная точка входа
"""

import asyncio
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

import config
from database import close_database, init_database, init_permanent_admin
from handlers import setup_all_handlers
from handlers.pair_management import stop_verification_cleanup
from services import (
    AuthService,
    MediaHandler,
    Monitor,
    PostForwarder,
    StorageService,
    TelegramService,
    VKService,
)
from utils.helpers import cleanup_all_temp_files
from utils.logger import logger, set_bot_instance

logger = logger.bind(module="main")

# =====
# Lock file management
# Управление lock-файлом
# =====


def create_lock_file():
    """Create lock file to prevent multiple instances"""
    if os.path.exists(config.config.lock_file):
        print(f"❌ Error: Bot is already running! Lock file exists: {config.config.lock_file}")
        sys.exit(1)

    try:
        with open(config.config.lock_file, "w") as f:
            f.write(str(os.getpid()))
        logger.info("lock_file_created", path=config.config.lock_file)
    except Exception as e:
        print(f"❌ Failed to create lock file: {e}")
        sys.exit(1)


def remove_lock_file():
    """Remove lock file"""
    try:
        if os.path.exists(config.config.lock_file):
            with open(config.config.lock_file, "r") as f:
                lock_pid = int(f.read().strip())

            if lock_pid == os.getpid():
                os.remove(config.config.lock_file)
                logger.info("lock_file_removed", path=config.config.lock_file)
    except Exception as e:
        logger.error("lock_file_removal_failed", error=str(e))


# =====
# Bot initialization
# Инициализация бота
# =====


async def main():
    """Main function"""
    # Create lock file / Создать lock-файл
    create_lock_file()

    # Cleanup old temporary files / Очистка старых временных файлов
    await cleanup_all_temp_files()

    bot = None
    monitor = None
    vk_service = None
    media_handler = None
    storage_service = None
    monitor_task = None

    try:
        # Initialize database / Инициализация базы данных
        await init_database()
        await init_permanent_admin()

        # Initialize bot / Инициализация бота
        bot = Bot(token=config.config.bot_token, default=DefaultBotProperties(parse_mode="HTML"))

        # Configure local API server if enabled / Настроить локальный API сервер
        if config.config.use_local_api and config.config.tg_api_server:
            from aiogram.client.session.aiohttp import AiohttpSession
            from aiogram.client.telegram import TelegramAPIServer

            local_server = TelegramAPIServer.from_base(config.config.tg_api_server)
            session = AiohttpSession(api=local_server)

            await bot.session.close()
            bot.session = session

            logger.info("local_api_configured", server=config.config.tg_api_server)
        else:
            logger.info("official_api_used")

        # Set bot instance for logger / Установить экземпляр бота для логгера
        set_bot_instance(bot)

        # Initialize FSM storage / Инициализация хранилища FSM
        storage = MemoryStorage()

        # Initialize dispatcher / Инициализация диспетчера
        dp = Dispatcher(storage=storage)

        # Initialize services as SHARED single instances (dependency injection).
        # Все сервисы создаются один раз и переиспользуются монитором и обработчиками.
        vk_service = VKService()
        await vk_service.init_session()

        telegram_service = TelegramService(bot)

        storage_service = StorageService()
        await storage_service.start_cache_flushing()

        auth_service = AuthService(bot)

        media_handler = MediaHandler()
        await media_handler.init_session()

        post_forwarder = PostForwarder(vk_service, telegram_service, media_handler)

        monitor = Monitor(
            bot,
            vk_service=vk_service,
            telegram_service=telegram_service,
            storage_service=storage_service,
            media_handler=media_handler,
            post_forwarder=post_forwarder,
        )

        # Setup handlers with shared services / Настройка обработчиков с общими сервисами
        setup_all_handlers(
            dp,
            bot,
            monitor=monitor,
            auth_service=auth_service,
            storage_service=storage_service,
            vk_service=vk_service,
            telegram_service=telegram_service,
            media_handler=media_handler,
            post_forwarder=post_forwarder,
        )

        # Register the native "Menu" button command list / Регистрация нативного меню команд
        from handlers.menu import set_bot_commands

        await set_bot_commands(bot)

        logger.info("bot_initialized")

        # Start monitor in background / Запустить монитор в фоне
        monitor_task = asyncio.create_task(monitor.start())

        try:
            # Start polling / Запустить polling
            logger.info("bot_polling_started")
            await dp.start_polling(bot)
        except KeyboardInterrupt:
            logger.info("bot_stopped_by_user")
        except Exception as e:
            logger.error("bot_error", error=str(e))
        finally:
            # Graceful shutdown / Graceful завершение
            logger.info("bot_shutdown_initiated")

            # Stop monitor / Остановить монитор
            if monitor:
                monitor.stop()

                logger.info("waiting_for_monitor")
                await monitor.wait_for_completion()

                # Wait for monitor task with extended timeout / Ждём задачу монитора с увеличенным timeout
                if monitor_task:
                    try:
                        await asyncio.wait_for(monitor_task, timeout=30)  # Увеличено с 10 до 30
                    except asyncio.TimeoutError:
                        logger.warning("monitor_shutdown_timeout")
                        monitor_task.cancel()
                        try:
                            await monitor_task
                        except asyncio.CancelledError:
                            logger.info("monitor_task_cancelled")

            # Stop verification cleanup / Остановить очистку верификаций
            stop_verification_cleanup()

            # Stop storage cache flushing / Остановить flush кэша хранилища
            if storage_service:
                await storage_service.stop_cache_flushing()

            # Close VK session / Закрыть VK сессию
            if vk_service:
                await vk_service.close_session()

            # Close media handler session / Закрыть сессию media handler
            if media_handler:
                await media_handler.close_session()

            # Close database / Закрыть базу данных
            await close_database()

            # Close bot session / Закрыть сессию бота
            if bot:
                await bot.session.close()

            # Final cleanup of temp files / Финальная очистка временных файлов
            await cleanup_all_temp_files()

            logger.info("bot_shutdown_complete")

    except Exception as e:
        logger.error("fatal_error", error=str(e), exc_info=True)
        raise

    finally:
        # Always remove lock file / Всегда удалять lock-файл
        remove_lock_file()


# =====
# Entry point
# Точка входа
# =====

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nℹ️  Bot stopped")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)
