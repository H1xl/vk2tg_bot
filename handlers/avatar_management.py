"""
Avatar management handlers
Обработчики управления аватарками
"""

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

from handlers.auth import require_auth
from handlers.interactive import get_command_arg, prompt_arg, register_action
from utils.helpers import calculate_image_hash, escape_html
from utils.logger import logger
from utils.messages import Messages

logger = logger.bind(module="avatar_management")

router = Router()

# Shared service instances (injected in setup_avatar_handlers) / Общие сервисы
vk_service = None
telegram_service = None
storage_service = None
media_handler = None

# =====
# /avatar command - force update channel avatar
# /avatar команда - принудительное обновление аватарки канала
# =====


@require_auth
async def cmd_update(message: Message, state: FSMContext):
    """Force update channel avatar from VK (prompts for pair id if omitted)"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "avatar")
        return
    await _run_avatar(message, arg, state)


async def _run_avatar(message: Message, arg: str, state: FSMContext):
    pair_id = arg.split()[0]

    # Get pair / Получить пару
    storage = storage_service
    pair = await storage.get_pair_by_id(pair_id)

    if not pair:
        await message.answer(
            Messages.UPDATE_PAIR_NOT_FOUND.format(pair_id=pair_id), parse_mode="HTML"
        )
        return

    processing_msg = await message.answer(
        Messages.UPDATE_STARTED.format(pair_id=pair_id), parse_mode="HTML"
    )

    vk_id = pair.vk_id
    tg_id = pair.tg_id

    try:
        # Get VK group avatar / Получить аватар группы VK
        avatar_url = await vk_service.get_group_photo(vk_id, size="photo_200")

        if not avatar_url:
            await processing_msg.delete()
            await message.answer(Messages.UPDATE_VK_FETCH_FAILED, parse_mode="HTML")
            logger.warning("update_vk_avatar_not_found", pair_id=pair_id, vk_id=vk_id)
            return

        # Download avatar / Скачать аватар
        avatar_path = await media_handler.download_photo(avatar_url, f"avatar_{vk_id}_update.jpg")

        if not avatar_path:
            await processing_msg.delete()
            await message.answer(Messages.UPDATE_DOWNLOAD_FAILED, parse_mode="HTML")
            logger.error("update_avatar_download_failed", pair_id=pair_id)
            return

        try:
            # Calculate hash / Вычислить хэш
            new_hash = await calculate_image_hash(avatar_path)

            if not new_hash:
                await processing_msg.delete()
                await message.answer(Messages.UPDATE_DOWNLOAD_FAILED, parse_mode="HTML")
                logger.error("update_avatar_hash_failed", pair_id=pair_id)
                return

            # Get old hash / Получить старый хэш
            avatar_info = await storage.get_avatar_info(pair_id)
            old_hash = avatar_info.get("hash") if avatar_info else None

            # Compare hashes / Сравнить хэши
            if old_hash and old_hash == new_hash:
                await processing_msg.delete()
                await message.answer(Messages.UPDATE_NO_CHANGE, parse_mode="HTML")
                logger.info("update_avatar_no_change", pair_id=pair_id)
                # Update timestamp even if no change / Обновить timestamp даже без изменений
                await storage.update_avatar_info(pair_id, new_hash)
                return

            # Update Telegram channel avatar / Обновить аватар канала Telegram
            success = await telegram_service.update_channel_avatar(tg_id, avatar_path)

            if success:
                # Update hash in database / Обновить хэш в БД
                await storage.update_avatar_info(pair_id, new_hash)

                await processing_msg.delete()
                await message.answer(Messages.UPDATE_SUCCESS, parse_mode="HTML")

                logger.info("avatar_updated_manual", pair_id=pair_id, user_id=message.from_user.id)
            else:
                await processing_msg.delete()
                await message.answer(Messages.UPDATE_TG_UPDATE_FAILED, parse_mode="HTML")
                logger.error("update_tg_update_failed", pair_id=pair_id)

        finally:
            # Cleanup downloaded file / Очистить скачанный файл
            await media_handler.cleanup_file(avatar_path)

    except Exception as e:
        logger.error(
            "update_avatar_error", pair_id=pair_id, user_id=message.from_user.id, error=str(e)
        )
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(
            Messages.UPDATE_ERROR.format(error=escape_html(str(e))), parse_mode="HTML"
        )


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_avatar_handlers(dp, vk_svc, telegram_svc, storage_svc, media_hdl):
    """Setup avatar management handlers with shared service instances"""
    global vk_service, telegram_service, storage_service, media_handler
    vk_service = vk_svc
    telegram_service = telegram_svc
    storage_service = storage_svc
    media_handler = media_hdl

    register_action("avatar", _run_avatar, Messages.PROMPT_PAIR_ID)

    router.message.register(cmd_update, Command("avatar", "av"))
    dp.include_router(router)
