"""
Utilities package
Пакет утилит
"""

from .error_handler import ErrorContext, handle_errors
from .helpers import (
    cleanup_all_temp_files,
    cleanup_temp_files,
    escape_html,
    format_file_size,
    format_progress_bar,
    format_text_for_telegram,
    generate_next_pair_id,
    sanitize_filename,
    split_long_text,
)
from .link_formatter import (
    format_channel_link,
    format_user_link,
    format_vk_group_link,
    format_vk_post_link,
    link_formatter,
)
from .logger import log_error, log_info, log_warning, logger, set_bot_instance
from .messages import Messages
from .retry_helper import (
    FILL_STRATEGY,
    MONITOR_STRATEGY,
    TELEGRAM_API_STRATEGY,
    retry_post_forward,
    retry_telegram_api,
    retry_with_backoff,
)
from .validators import (
    InviteCodeModel,
    PairCreateModel,
    ReportModel,
    validate_is_safe,
    validate_pair_id,
    validate_pair_name,
    validate_tg_id,
    validate_vk_id,
)

__all__ = [
    "logger",
    "log_error",
    "log_info",
    "log_warning",
    "set_bot_instance",
    "format_text_for_telegram",
    "escape_html",
    "split_long_text",
    "cleanup_temp_files",
    "cleanup_all_temp_files",
    "generate_next_pair_id",
    "format_file_size",
    "sanitize_filename",
    "format_progress_bar",
    "link_formatter",
    "format_user_link",
    "format_channel_link",
    "format_vk_post_link",
    "format_vk_group_link",
    "retry_post_forward",
    "retry_telegram_api",
    "retry_with_backoff",
    "MONITOR_STRATEGY",
    "FILL_STRATEGY",
    "TELEGRAM_API_STRATEGY",
    "handle_errors",
    "ErrorContext",
    "validate_vk_id",
    "validate_tg_id",
    "validate_pair_name",
    "validate_pair_id",
    "validate_is_safe",
    "PairCreateModel",
    "InviteCodeModel",
    "ReportModel",
    "Messages",
]
