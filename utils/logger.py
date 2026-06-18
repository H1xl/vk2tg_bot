"""
Logging module with Structlog
Модуль логирования с Structlog
"""

import logging
from collections import OrderedDict, deque
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler

import structlog

import config

# =====
# Custom renderer for human-readable logs
# Кастомный рендерер для читаемых логов
# =====


def human_readable_renderer(logger, name, event_dict):
    """
    Render logs in format: [time][level][module][function] event key1=val1 key2=val2
    """
    # Extract timestamp / Извлечь timestamp
    timestamp = event_dict.pop("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    # Extract level / Извлечь уровень
    level = event_dict.pop("level", "info").upper()

    # Extract module from event_dict (set by bind) / Извлечь модуль из event_dict
    module = event_dict.pop("module", "root")

    # Extract event (main message) / Извлечь событие
    event = event_dict.pop("event", "")

    # Extract function name if available / Извлечь имя функции
    func_name = event_dict.pop("func_name", None)

    # Build function part / Построить часть функции
    func_part = f".{func_name}" if func_name else ""

    # Build main part / Построить основную часть
    main = f"[{timestamp}][{level:5s}][{module}{func_part}] {event}"

    # Add remaining key-value pairs / Добавить оставшиеся пары ключ-значение
    if event_dict:
        extras = " ".join(
            f"{k}={v}" for k, v in event_dict.items() if k not in ["exception", "exc_info"]
        )
        main = f"{main} {extras}"

    # Add exception if present / Добавить исключение если есть
    exception = event_dict.get("exception")
    if exception:
        main = f"{main}\n{exception}"

    return main


# =====
# Prevent duplicate handler setup
# Предотвращение дублирования обработчиков
# =====

_logger_initialized = False


def _init_logging():
    """Initialize logging only once"""
    global _logger_initialized

    if _logger_initialized:
        return

    _logger_initialized = True

    # Clear existing handlers to prevent duplicates / Очистка существующих обработчиков
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.propagate = False

    # Custom formatter for standard logging / Кастомный форматтер для стандартного логирования
    class CustomFormatter(logging.Formatter):
        def format(self, record):
            # Check if already formatted by structlog / Проверка форматирования structlog
            message = record.getMessage()
            if message.startswith("["):
                # Already formatted by structlog, return as-is / Уже отформатирован
                return message

            # Format aiogram and other standard logs / Форматирование aiogram и других логов
            timestamp = self.formatTime(record, "%Y-%m-%d %H:%M:%S")
            level = record.levelname
            module = record.name.split(".")[-1] if "." in record.name else record.name
            return f"[{timestamp}][{level:5s}][{module}] {message}"

    formatter = CustomFormatter()

    # File handler / Обработчик файлов
    file_handler = RotatingFileHandler(
        config.config.log_file,
        maxBytes=config.config.log_max_bytes,
        backupCount=config.config.log_backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(getattr(logging, config.config.log_level, logging.INFO))
    file_handler.setFormatter(formatter)

    # Console handler / Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, config.config.log_level, logging.INFO))
    console_handler.setFormatter(formatter)

    # Add handlers to root logger / Добавление обработчиков
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    root_logger.setLevel(getattr(logging, config.config.log_level, logging.INFO))

    # Configure Structlog with human-readable renderer / Настройка Structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="%Y-%m-%d %H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            human_readable_renderer,  # Use custom renderer
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


# Initialize on import / Инициализация при импорте
_init_logging()

# Get logger / Получить логгер
logger = structlog.get_logger()

# =====
# Error tracking with fixed size
# Отслеживание ошибок с фиксированным размером
# =====

error_history = deque(maxlen=config.config.error_history_size)


def add_error(message: str):
    """Add error to history with size limit"""

    if len(message) > config.config.max_error_message_length:
        message = message[: config.config.max_error_message_length] + "..."

    error_history.append({"timestamp": datetime.now(), "message": message})


def get_errors_last_24h() -> int:
    """Get error count from last 24 hours"""

    cutoff = datetime.now() - timedelta(hours=24)
    return sum(1 for err in error_history if err["timestamp"] >= cutoff)


def get_last_errors(count: int = 5) -> list:
    """Get last N errors"""

    errors = list(error_history)[-count:]
    return [
        f"[{err['timestamp'].strftime('%Y-%m-%d %H:%M:%S')}] {err['message']}" for err in errors
    ]


# =====
# Critical error notification with memory leak fix
# Уведомление о критических ошибках с исправлением утечки памяти
# =====

_bot_instance = None
_last_critical_errors = OrderedDict()
_CRITICAL_ERROR_COOLDOWN = 300


def set_bot_instance(bot):
    """Set bot instance for error notifications"""
    global _bot_instance
    _bot_instance = bot


async def log_error(message: str, is_critical: bool = False):
    """Log error and optionally send to error channel"""

    logger.error("error", message=message)
    add_error(message)

    if is_critical and _bot_instance:
        current_time = datetime.now()
        error_key = message[:100]

        # Check cooldown / Проверка cooldown
        if error_key in _last_critical_errors:
            time_since_last = (current_time - _last_critical_errors[error_key]).total_seconds()
            if time_since_last < _CRITICAL_ERROR_COOLDOWN:
                return

        # Clean old entries to prevent memory leak / Очистка старых записей
        if len(_last_critical_errors) >= config.config.max_critical_errors_cache:
            _last_critical_errors.popitem(last=False)

        try:
            display_message = message if len(message) <= 500 else message[:500] + "..."

            await _bot_instance.send_message(
                config.config.error_channel_id,
                f"<b>CRITICAL ERROR:</b>\n<pre>{display_message}</pre>",
                parse_mode="HTML",
            )
            _last_critical_errors[error_key] = current_time
        except Exception as e:
            logger.error("error_notification_failed", error=str(e))


def log_info(message: str):
    """Log info message"""
    logger.info("info", message=message)


def log_warning(message: str):
    """Log warning message"""
    logger.warning("warning", message=message)
