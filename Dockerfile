# syntax=docker/dockerfile:1
#
# VK -> Telegram forwarding bot
# Бот пересылки постов VK -> Telegram
#
# Build:  docker build -t vk2tg-bot .
# Run:    docker compose up -d   (see DOCKER.md)

FROM python:3.13-slim

# System deps:
#  - ffmpeg: required by yt-dlp for video processing / нужен yt-dlp для видео
#  - tini:   proper PID 1 (signal forwarding + reaping ffmpeg subprocesses)
# Системные зависимости: ffmpeg (видео) и tini (корректный PID 1).
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg tini \
    && rm -rf /var/lib/apt/lists/*

# Python runtime hygiene / Гигиена окружения Python
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install dependencies first (better layer caching) / Сначала зависимости — для кэша слоёв
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Application code / Код приложения
COPY . .

# Runtime data directories (also mounted as volumes in compose) / Каталоги данных
# storage/ holds the SQLite DB (storage/bot.db) — must persist.
RUN mkdir -p storage logs downloads

# Run as non-root / Запуск под непривилегированным пользователем
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# tini as init: forwards SIGTERM to Python (graceful shutdown) and reaps zombies.
# tini как init: пробрасывает SIGTERM в Python (грейсфул-стоп) и собирает зомби-процессы.
ENTRYPOINT ["/usr/bin/tini", "--"]

# Remove a stale lock left by an unclean stop, then start the bot as PID-forwarded process.
# The container itself guarantees single-instance, so dropping a stale .bot.lock on start is safe.
# Удаляем устаревший lock от нечистой остановки и запускаем бота (контейнер сам гарантирует один экземпляр).
CMD ["sh", "-c", "rm -f /app/.bot.lock; exec python -u main.py"]
