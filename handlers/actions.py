"""
Action handlers with HTML formatting
Обработчики действий с HTML форматированием
"""

import asyncio
import random
import shlex
import string
from datetime import datetime
from math import ceil
from typing import Dict

from aiogram import Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message

import config
from handlers.auth import require_auth
from handlers.interactive import get_command_arg, prompt_arg, register_action
from utils.helpers import escape_html, format_progress_bar
from utils.link_formatter import format_vk_post_link
from utils.logger import logger
from utils.messages import Messages
from utils.retry_helper import FILL_STRATEGY, retry_post_forward

router = Router()

# Shared service instances (injected in setup_action_handlers) / Общие сервисы
monitor = None
storage_service = None
vk_service = None
telegram_service = None
media_handler = None
post_forwarder = None

# =====
# /backfill command
# Команда /backfill
# =====


@require_auth
async def cmd_fill(message: Message, state: FSMContext):
    """Backfill posts from VK to Telegram (prompts for pair id if omitted)"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "backfill")
        return
    await _run_backfill(message, arg, state)


async def _run_backfill(message: Message, arg: str, state: FSMContext):
    """Run backfill for an argument string of the form 'pair_id [count]'"""
    parts = arg.split()
    pair_id = parts[0]

    count = 100
    if len(parts) > 1:
        try:
            count = int(parts[1])
        except ValueError:
            await message.answer(
                Messages.FILL_INVALID_COUNT.format(value=escape_html(parts[1])), parse_mode="HTML"
            )
            return

    if count < 1 or count > 100:
        await message.answer(Messages.FILL_COUNT_RANGE, parse_mode="HTML")
        return

    storage = storage_service
    pair = await storage.get_pair_by_id(pair_id)

    if not pair:
        await message.answer(
            Messages.FILL_PAIR_NOT_FOUND.format(pair_id=pair_id), parse_mode="HTML"
        )
        return

    processing_msg = await message.answer(
        Messages.FILL_STARTED.format(count=count, pair_id=pair_id), parse_mode="HTML"
    )

    vk_id = pair.vk_id
    tg_id = pair.tg_id
    is_safe = pair.is_safe

    try:
        posts = await vk_service.get_posts(vk_id, count=count)

        if not posts:
            await processing_msg.delete()
            await message.answer(Messages.FILL_NO_POSTS, parse_mode="HTML")
            return

        filtered_posts = []
        for post in posts:
            if post.get("is_pinned") or post.get("marked_as_ads") or "copy_history" in post:
                continue
            filtered_posts.append(post)

        if not filtered_posts:
            await processing_msg.delete()
            await message.answer(Messages.FILL_NO_POSTS_AFTER_FILTER, parse_mode="HTML")
            return

        filtered_posts.reverse()

        success_count = 0
        error_count = 0
        skipped_ads_count = 0
        last_post_id = None
        error_details = []

        total_posts = len(filtered_posts)
        last_update_percent = 0

        for i, post in enumerate(filtered_posts, 1):
            try:
                post_id = post.get("id")

                if not is_safe:
                    # Reuse the shared monitor so its ad-check cache is effective
                    # Переиспользуем общий monitor (его кэш проверки рекламы работает)
                    is_safe_post = await monitor.check_post_for_ads(vk_id, post_id)

                    if not is_safe_post:
                        skipped_ads_count += 1
                        last_post_id = post_id
                        logger.info(
                            "fill_post_skipped_ad",
                            post_id=post_id,
                            pair_id=pair_id,
                            vk_url=format_vk_post_link(vk_id, post_id),
                        )
                        await storage.set_last_post(pair_id, post_id)
                        continue

                async def forward_func():
                    return await post_forwarder.forward_post(post, tg_id)

                forwarded, _ = await retry_post_forward(
                    forward_func, FILL_STRATEGY, log_prefix=f"fill_{pair_id}"
                )

                if forwarded:
                    success_count += 1
                    last_post_id = post_id
                    await storage.set_last_post(pair_id, last_post_id)
                else:
                    error_count += 1
                    last_post_id = post_id
                    error_details.append(
                        Messages.FILL_ERROR_ITEM.format(
                            post_id=post_id, url=format_vk_post_link(vk_id, post_id)
                        )
                    )
                    await storage.set_last_post(pair_id, last_post_id)

                current_percent = int((i / total_posts) * 100)
                if current_percent >= last_update_percent + 5 or i == total_posts:
                    display_percent = (current_percent // 5) * 5

                    try:
                        progress_bar = format_progress_bar(i, total_posts)

                        await processing_msg.edit_text(
                            Messages.FILL_PROGRESS.format(
                                progress_bar=progress_bar,
                                current=i,
                                total=total_posts,
                                percent=display_percent,
                                success=success_count,
                                skipped_ads=skipped_ads_count,
                                errors=error_count,
                            ),
                            parse_mode="HTML",
                        )
                        last_update_percent = display_percent
                    except Exception:
                        pass

                await asyncio.sleep(2.5)

            except Exception as e:
                error_count += 1
                logger.error("fill_post_error", post_id=post.get("id"), error=str(e))
                continue

        try:
            await processing_msg.delete()
        except Exception:
            pass

        # Persist to DB for durability. Do NOT clear the cache: the monitor shares this
        # StorageService instance and must keep seeing the updated last_post_id, otherwise
        # it would re-read a stale value and re-fetch up to 100 posts (the reported bug).
        # Сбрасываем в БД, но НЕ чистим кэш: монитор использует тот же StorageService и
        # должен видеть обновлённый last_post_id (иначе снова возьмёт 100 постов).
        await storage._flush_to_db()
        logger.info("fill_cache_flushed", pair_id=pair_id, last_post_id=last_post_id)

        report_text = Messages.FILL_COMPLETE.format(
            total=total_posts,
            success=success_count,
            skipped_ads=skipped_ads_count,
            errors=error_count,
        )

        if error_details:
            report_text += Messages.FILL_ERRORS_DETAIL + "\n".join(error_details[:10])
            if len(error_details) > 10:
                report_text += Messages.LIST_MORE_ERRORS.format(count=len(error_details) - 10)

        await message.answer(report_text, parse_mode="HTML")

        logger.info(
            "fill_completed",
            pair_id=pair_id,
            user_id=message.from_user.id,
            success=success_count,
            skipped_ads=skipped_ads_count,
            errors=error_count,
            final_last_post_id=last_post_id,
        )

    except Exception as e:
        logger.error("fill_error", pair_id=pair_id, user_id=message.from_user.id, error=str(e))
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer(
            Messages.FILL_ERROR.format(error=escape_html(str(e))), parse_mode="HTML"
        )


# =====
# /broadcast command
# Команда /broadcast
# =====


@require_auth
async def cmd_notice(message: Message, state: FSMContext):
    """Broadcast a message to all active pairs (prompts for text if omitted)"""
    arg = get_command_arg(message.text)
    if not arg:
        await prompt_arg(message, state, "broadcast")
        return
    await _run_broadcast(message, arg, state)


async def _run_broadcast(message: Message, arg: str, state: FSMContext):
    notice_text = arg

    if len(notice_text) > 4096:
        await message.answer(Messages.NOTICE_TOO_LONG, parse_mode="HTML")
        return

    active_pairs = await storage_service.get_active_pairs()

    if not active_pairs:
        await message.answer(Messages.NOTICE_NO_ACTIVE_PAIRS, parse_mode="HTML")
        return

    notice_preview = notice_text[:200]
    if len(notice_text) > 200:
        notice_preview += "..."

    processing_msg = await message.answer(
        Messages.NOTICE_STARTED.format(count=len(active_pairs), text=escape_html(notice_preview)),
        parse_mode="HTML",
    )

    success_count = 0
    error_count = 0
    total_pairs = len(active_pairs)
    last_update_percent = 0

    for idx, pair in enumerate(active_pairs, 1):
        try:
            tg_id = pair.tg_id
            pair_name = pair.name or pair.id

            logger.info("notice_sending", idx=idx, total=total_pairs, pair_name=pair_name)

            # Escape the admin-provided text so '<', '&' etc. don't break HTML parsing.
            # Экранируем текст уведомления, чтобы спецсимволы не ломали HTML-разметку.
            result, retry_after = await telegram_service.send_message(
                tg_id, Messages.NOTICE_BROADCAST.format(text=escape_html(notice_text))
            )

            if result:
                success_count += 1
                logger.info("notice_sent", pair_name=pair_name)
            else:
                error_count += 1
                logger.error("notice_send_failed", pair_name=pair_name, retry_after=retry_after)

            current_percent = int((idx / total_pairs) * 100)
            if current_percent >= last_update_percent + 5 or idx == total_pairs:
                display_percent = (current_percent // 5) * 5

                try:
                    progress_bar = format_progress_bar(idx, total_pairs)

                    await processing_msg.edit_text(
                        Messages.NOTICE_PROGRESS.format(
                            progress_bar=progress_bar,
                            current=idx,
                            total=total_pairs,
                            percent=display_percent,
                            success=success_count,
                            errors=error_count,
                        ),
                        parse_mode="HTML",
                    )
                    last_update_percent = display_percent
                except Exception:
                    pass

            await asyncio.sleep(1.5)

        except Exception as e:
            error_count += 1
            logger.error("notice_error", pair_id=pair.id, error=str(e))
            continue

    try:
        await processing_msg.delete()
    except Exception:
        pass

    await message.answer(
        Messages.NOTICE_COMPLETE.format(
            total=total_pairs, success=success_count, errors=error_count
        ),
        parse_mode="HTML",
    )

    logger.info(
        "notice_broadcast_complete",
        user_id=message.from_user.id,
        success=success_count,
        total=total_pairs,
    )


# =====
# Setup handlers
# Настройка обработчиков
# =====


def setup_action_handlers(
    dp,
    monitor,
    storage_service,
    vk_service,
    telegram_service,
    media_handler,
    post_forwarder,
):
    """Setup action handlers with shared service instances"""
    _bind_services(
        monitor, storage_service, vk_service, telegram_service, media_handler, post_forwarder
    )

    # Register interactive actions / Регистрация интерактивных действий
    register_action("backfill", _run_backfill, Messages.PROMPT_BACKFILL)
    register_action("broadcast", _run_broadcast, Messages.PROMPT_BROADCAST)

    router.message.register(cmd_fill, Command("backfill", "bf"))
    router.message.register(cmd_notice, Command("broadcast", "bc"))
    dp.include_router(router)


def _bind_services(
    monitor_, storage_service_, vk_service_, telegram_service_, media_handler_, post_forwarder_
):
    """Bind shared services to module globals"""
    global monitor, storage_service, vk_service, telegram_service, media_handler, post_forwarder
    monitor = monitor_
    storage_service = storage_service_
    vk_service = vk_service_
    telegram_service = telegram_service_
    media_handler = media_handler_
    post_forwarder = post_forwarder_
