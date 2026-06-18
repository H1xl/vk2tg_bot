"""
Handlers package
Пакет обработчиков
"""

from .admin import setup_admin_handlers
from .auth import setup_auth_handlers
from .user import setup_user_handlers


def setup_all_handlers(
    dp,
    bot,
    monitor,
    auth_service,
    storage_service,
    vk_service,
    telegram_service,
    media_handler,
    post_forwarder,
):
    """
    Setup all handlers with SHARED service instances.
    Must be called after all services are initialized.
    Настройка всех обработчиков с общими экземплярами сервисов.
    """
    # Auth handlers
    setup_auth_handlers(dp, auth_service)

    # Admin handlers
    setup_admin_handlers(dp, auth_service)

    # User handlers
    setup_user_handlers(dp, auth_service, storage_service)

    # Import and setup other handlers
    from .actions import setup_action_handlers
    from .avatar_management import setup_avatar_handlers
    from .interactive import setup_interactive_handlers
    from .menu import setup_menu_handlers
    from .pair_management import setup_pair_handlers
    from .system import setup_system_handlers

    # Interactive argument prompting (shared waiting state) / Запрос параметров
    setup_interactive_handlers(dp)

    setup_system_handlers(dp, monitor, storage_service)
    setup_pair_handlers(dp, bot, vk_service, telegram_service, storage_service, media_handler)
    setup_action_handlers(
        dp,
        monitor=monitor,
        storage_service=storage_service,
        vk_service=vk_service,
        telegram_service=telegram_service,
        media_handler=media_handler,
        post_forwarder=post_forwarder,
    )
    setup_avatar_handlers(dp, vk_service, telegram_service, storage_service, media_handler)

    # Menu handlers must be registered LAST so its button-label text dispatcher
    # runs only after every command handler has had a chance to match.
    # Меню регистрируется ПОСЛЕДНИМ, чтобы перехват меток кнопок шёл после команд.
    setup_menu_handlers(dp, auth_service)


__all__ = [
    "setup_all_handlers",
]
