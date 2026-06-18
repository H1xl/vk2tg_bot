"""
Configuration module
Модуль конфигурации
"""

import os
import sys

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Bot settings with Pydantic validation"""

    # =====
    # Telegram Configuration
    # Конфигурация Telegram
    # =====

    bot_token: str = Field(..., description="Telegram Bot Token")
    use_local_api: bool = Field(True, description="Use local Telegram Bot API")
    tg_api_server: str = Field("http://127.0.0.1:8081", description="Local API server URL")
    error_channel_id: int = Field(..., description="Channel ID for errors")
    report_channel_id: int = Field(..., description="Channel ID for user reports")

    # =====
    # VK API Configuration
    # Конфигурация VK API
    # =====

    vk_token: str = Field(..., description="VK Service Token")
    vk_api_version: str = Field("5.131")
    vk_api_url: str = Field("https://api.vk.com/method/")

    # =====
    # Network / SSL
    # Сеть / SSL
    # =====

    # Verify TLS certificates for outbound HTTP (VK API + media downloads).
    # Set to False ONLY for tests (e.g. behind a proxy / self-signed certs).
    # Проверка TLS-сертификатов исходящих запросов; False — только для тестов.
    verify_ssl: bool = Field(True, description="Verify TLS certificates for outbound HTTP")

    # =====
    # Authentication
    # Аутентификация
    # =====

    admin_user_id: int = Field(..., description="Permanent admin user ID")

    # =====
    # Monitoring Configuration
    # Конфигурация мониторинга
    # =====

    monitor_interval: int = Field(60, description="Monitor check interval in seconds")
    cache_flush_interval: int = Field(10, description="Write-back cache flush interval")

    # =====
    # Logging Configuration
    # Конфигурация логирования
    # =====

    log_level: str = Field("DEBUG", description="Logging level")
    log_dir: str = Field("logs")
    log_file: str = Field("logs/bot.log")
    log_max_bytes: int = Field(2_000_000)
    log_backup_count: int = Field(5)
    show_db_logs: bool = Field(False, description="Show database SQL logs")

    # =====
    # Storage Configuration
    # Конфигурация хранилища
    # =====

    storage_dir: str = Field("storage")
    downloads_dir: str = Field("downloads")

    # =====
    # Telegram Limits
    # Лимиты Telegram
    # =====

    tg_max_file_size: int = Field(2_000_000_000)
    tg_media_group_limit: int = Field(10)
    tg_max_caption_length: int = Field(1024)
    tg_requests_per_second: float = Field(30.0)
    tg_messages_per_minute_per_chat: int = Field(20)

    # =====
    # VK API Limits
    # Лимиты VK API
    # =====

    vk_requests_per_second: float = Field(3.0)
    vk_max_posts_per_request: int = Field(100)

    # =====
    # Retry Configuration
    # Конфигурация повторных попыток
    # =====

    max_retry_attempts: int = Field(5)
    retry_delays: list[int] = Field([30, 60, 120, 240, 480])

    # =====
    # Media Configuration
    # Конфигурация медиа
    # =====

    ytdlp_timeout: int = Field(300)
    max_error_message_length: int = Field(200)
    error_history_size: int = Field(50)

    # =====
    # Semaphore Limits
    # Лимиты семафора
    # =====

    max_concurrent_video_downloads: int = Field(3)
    max_concurrent_photo_downloads: int = Field(10)
    max_concurrent_audio_downloads: int = Field(5)

    # =====
    # Cache Configuration
    # Конфигурация кэша
    # =====

    video_cache_size: int = Field(20_000)
    video_cache_ttl_hours: int = Field(24)
    checked_posts_cache_size: int = Field(10_000)
    checked_posts_cache_ttl_hours: int = Field(1)
    max_critical_errors_cache: int = Field(100)

    # =====
    # Pagination Configuration
    # Конфигурация пагинации
    # =====

    pairs_per_page: int = Field(5)

    # =====
    # Pair Verification
    # Верификация пар
    # =====

    pair_verification_timeout: int = Field(300)
    pair_verification_check_interval: int = Field(15)

    # =====
    # Ad Check Configuration
    # Конфигурация проверки рекламы
    # =====

    comments_to_check: int = Field(5)
    cache_overflow_cooldown_hours: int = Field(1)
    # Delay before checking comments of a NEW post in an unsafe pair, so ads
    # posted shortly after publication appear in comments before the check.
    # Задержка перед проверкой комментариев нового поста в небезопасной паре.
    ad_check_delay_minutes: int = Field(
        15, description="Delay before ad-check of a new post (unsafe pairs)"
    )

    # =====
    # Avatar Update Configuration
    # Конфигурация обновления аватарок
    # =====

    avatar_update_interval_hours: int = Field(
        24, description="Interval for automatic avatar updates"
    )
    avatar_check_on_monitor_cycles: int = Field(
        60, description="Check avatars every N monitor cycles"
    )

    # =====
    # Web Server Configuration
    # Конфигурация веб-сервера
    # =====

    web_port: int = Field(8080)
    web_auth_token: str = Field(..., description="Token for /health endpoint")

    # =====
    # User Reports Configuration
    # Конфигурация пользовательских репортов
    # =====

    report_rate_limit_per_hour: int = Field(5)

    # =====
    # User Rate Limiting
    # Ограничение частоты для пользователей
    # =====

    user_commands_rate_limit: int = Field(10, description="Commands per minute for regular users")

    # =====
    # Temporary Files Configuration
    # Конфигурация временных файлов
    # =====

    temp_file_max_age: int = Field(3600)
    lock_file: str = Field(".bot.lock")
    storage_backup_count: int = Field(3)

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)

        # Recalculate limits based on use_local_api / Пересчёт лимитов
        if not self.use_local_api:
            self.tg_max_file_size = 50_000_000
            self.tg_requests_per_second = 20.0

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v: str) -> str:
        """Validate logging level"""
        valid_levels = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        v = v.upper()
        if v not in valid_levels:
            raise ValueError(f"log_level must be one of {valid_levels}")
        return v

    @field_validator("monitor_interval")
    @classmethod
    def validate_monitor_interval(cls, v: int) -> int:
        """Validate monitor interval"""
        if v < 10:
            raise ValueError("monitor_interval must be >= 10 seconds")
        if v > 3600:
            raise ValueError("monitor_interval must be <= 3600 seconds")
        return v

    @field_validator("cache_flush_interval")
    @classmethod
    def validate_cache_flush_interval(cls, v: int) -> int:
        """Validate cache flush interval"""
        if v < 5:
            raise ValueError("cache_flush_interval must be >= 5 seconds")
        if v > 300:
            raise ValueError("cache_flush_interval must be <= 300 seconds")
        return v

    @field_validator("tg_requests_per_second")
    @classmethod
    def validate_tg_requests_per_second(cls, v: float) -> float:
        """Validate Telegram requests per second"""
        if v <= 0:
            raise ValueError("tg_requests_per_second must be > 0")
        if v > 30:
            raise ValueError("tg_requests_per_second should not exceed 30 to avoid rate limits")
        return v

    @field_validator("vk_requests_per_second")
    @classmethod
    def validate_vk_requests_per_second(cls, v: float) -> float:
        """Validate VK requests per second"""
        if v <= 0:
            raise ValueError("vk_requests_per_second must be > 0")
        if v > 3:
            raise ValueError("vk_requests_per_second should not exceed 3 (VK API limit)")
        return v

    @field_validator("max_retry_attempts")
    @classmethod
    def validate_max_retry_attempts(cls, v: int) -> int:
        """Validate max retry attempts"""
        if v < 1:
            raise ValueError("max_retry_attempts must be >= 1")
        if v > 10:
            raise ValueError("max_retry_attempts should not exceed 10")
        return v

    @field_validator("video_cache_size")
    @classmethod
    def validate_video_cache_size(cls, v: int) -> int:
        """Validate video cache size"""
        if v < 100:
            raise ValueError("video_cache_size must be >= 100")
        if v > 100_000:
            raise ValueError("video_cache_size should not exceed 100000 to prevent memory issues")
        return v

    @field_validator("checked_posts_cache_size")
    @classmethod
    def validate_checked_posts_cache_size(cls, v: int) -> int:
        """Validate checked posts cache size"""
        if v < 100:
            raise ValueError("checked_posts_cache_size must be >= 100")
        if v > 50_000:
            raise ValueError("checked_posts_cache_size should not exceed 50000")
        return v

    @field_validator("pairs_per_page")
    @classmethod
    def validate_pairs_per_page(cls, v: int) -> int:
        """Validate pairs per page"""
        if v < 1:
            raise ValueError("pairs_per_page must be >= 1")
        if v > 20:
            raise ValueError("pairs_per_page should not exceed 20 for better UX")
        return v

    @field_validator("report_rate_limit_per_hour")
    @classmethod
    def validate_report_rate_limit(cls, v: int) -> int:
        """Validate report rate limit"""
        if v < 1:
            raise ValueError("report_rate_limit_per_hour must be >= 1")
        if v > 50:
            raise ValueError("report_rate_limit_per_hour should not exceed 50")
        return v

    @field_validator("user_commands_rate_limit")
    @classmethod
    def validate_user_commands_rate_limit(cls, v: int) -> int:
        """Validate user commands rate limit"""
        if v < 1:
            raise ValueError("user_commands_rate_limit must be >= 1")
        if v > 60:
            raise ValueError("user_commands_rate_limit should not exceed 60")
        return v

    @field_validator("avatar_update_interval_hours")
    @classmethod
    def validate_avatar_update_interval(cls, v: int) -> int:
        """Validate avatar update interval"""
        if v < 1:
            raise ValueError("avatar_update_interval_hours must be >= 1")
        if v > 168:
            raise ValueError("avatar_update_interval_hours should not exceed 168 (1 week)")
        return v

    @field_validator("avatar_check_on_monitor_cycles")
    @classmethod
    def validate_avatar_check_cycles(cls, v: int) -> int:
        """Validate avatar check cycles"""
        if v < 1:
            raise ValueError("avatar_check_on_monitor_cycles must be >= 1")
        if v > 1440:
            raise ValueError("avatar_check_on_monitor_cycles should not exceed 1440")
        return v


# =====
# Global configuration instance
# Глобальный экземпляр конфигурации
# =====

try:
    config = Settings()
except Exception as e:
    print(f"❌ Configuration error: {e}")
    sys.exit(1)

# =====
# Create necessary directories
# Создание необходимых директорий
# =====

for directory in [config.log_dir, config.storage_dir, config.downloads_dir]:
    os.makedirs(directory, exist_ok=True)
