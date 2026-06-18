# 🐳 Docker: упаковка, распаковка и запуск

Инструкция по сборке, запуску и переносу бота VK → Telegram в Docker.

---

## 1. Предварительные требования

- Установлен **Docker** (с плагином **Docker Compose v2**): `docker --version`, `docker compose version`.
- Подготовлен файл **`.env`** в корне проекта (скопируйте из `.env.example` и заполните):

  ```bash
  cp .env.example .env
  # отредактируйте BOT_TOKEN, VK_TOKEN, ADMIN_USER_ID, *_CHANNEL_ID, WEB_AUTH_TOKEN
  ```

> ⚠️ `.env` **не** попадает в образ (исключён в `.dockerignore`) — секреты передаются только через `env_file` при запуске.

### Важно про локальный Telegram API

По умолчанию в `.env.example` стоит `USE_LOCAL_API=true` и `TG_API_SERVER=http://127.0.0.1:8081`.
Внутри контейнера `127.0.0.1` — это сам контейнер, поэтому есть два варианта:

- **Проще (официальный API):** в `.env` поставьте `USE_LOCAL_API=false`. Лимит файла — 50 МБ.
- **Локальный API (файлы до ~2 ГБ):** раскомментируйте сервис `telegram-bot-api` в [docker-compose.yml](docker-compose.yml), задайте `TELEGRAM_API_ID`/`TELEGRAM_API_HASH`, а в `.env` укажите
  `USE_LOCAL_API=true` и `TG_API_SERVER=http://telegram-bot-api:8081`.

---

## 2. Сборка и запуск (на месте)

```bash
# Собрать образ и запустить в фоне
docker compose up -d --build

# Логи (Ctrl+C для выхода из просмотра)
docker compose logs -f bot

# Остановить
docker compose down

# Перезапустить после изменений в коде
docker compose up -d --build
```

Данные (БД, логи, скачанные файлы) сохраняются на хосте в каталогах `./storage`, `./logs`, `./downloads` (тома в compose). БД SQLite лежит в **`storage/bot.db`**.

---

## 3. Упаковка проекта для переноса

Есть два способа доставить бота на другую машину.

### Вариант A — перенос исходников (рекомендуется)

Сборка образа выполняется уже на целевой машине. Самый гибкий путь.

```bash
# Заархивировать проект БЕЗ venv/данных/секретов
# (на Linux/Git Bash)
tar --exclude='venv' --exclude='storage' --exclude='downloads' \
    --exclude='logs' --exclude='__pycache__' --exclude='.git' \
    --exclude='.env' --exclude='.bot.lock' \
    -czf vk2tg-bot-src.tar.gz .
```

На Windows (PowerShell) можно просто упаковать в zip, исключив тяжёлые/секретные каталоги:

```powershell
# Временно убедитесь, что копируете без venv/storage/downloads/logs/.env
Compress-Archive -Path * -DestinationPath vk2tg-bot-src.zip
```

**Распаковка и запуск на целевой машине:**

```bash
tar -xzf vk2tg-bot-src.tar.gz -C vk2tg-bot && cd vk2tg-bot
cp .env.example .env      # затем заполнить .env
docker compose up -d --build
```

### Вариант B — перенос готового образа (offline, без интернета на цели)

Собираем образ на одной машине, переносим файлом, грузим на другой.

```bash
# 1) Собрать образ
docker build -t vk2tg-bot:latest .

# 2) Сохранить образ в архив (упаковка)
docker save vk2tg-bot:latest | gzip > vk2tg-bot-image.tar.gz

# 3) Перенести vk2tg-bot-image.tar.gz + docker-compose.yml + .env на целевую машину
```

**Распаковка на целевой машине:**

```bash
# 4) Загрузить образ из архива
docker load < vk2tg-bot-image.tar.gz

# 5) Рядом положить docker-compose.yml и .env, затем запустить БЕЗ пересборки
docker compose up -d
```

> Compose возьмёт уже загруженный образ `vk2tg-bot:latest` (он указан в `image:`), а не будет собирать заново.

---

## 4. Резервное копирование и восстановление данных

Всё состояние бота — это каталог **`storage/`** (в нём `bot.db`).

```bash
# Бэкап (можно на лету; SQLite переживает копирование файла в покое)
docker compose stop bot
tar -czf vk2tg-data-backup.tar.gz storage/
docker compose start bot

# Восстановление
docker compose down
tar -xzf vk2tg-data-backup.tar.gz
docker compose up -d
```

---

## 5. Обновление

```bash
# Обновили код/зависимости -> пересобрать и поднять
docker compose up -d --build

# Обновить базовый образ Python и системные пакеты
docker compose build --pull
docker compose up -d
```

---

## 6. Полезные команды

```bash
docker compose ps                 # статус
docker compose logs --tail=200 bot
docker compose exec bot sh        # шелл внутри контейнера
docker stats vk2tg-bot            # потребление ресурсов
```

---

## 7. Особенности и заметки

- **Один экземпляр.** Бот защищён lock-файлом. В контейнере единственность гарантирует сам контейнер, поэтому при старте устаревший `.bot.lock` (после нечистой остановки) автоматически удаляется — см. `CMD` в [Dockerfile](Dockerfile). **Не** запускайте две копии на одной БД.
- **Грейсфул-стоп.** `tini` пробрасывает `SIGTERM` в Python — `docker compose down` завершает текущий цикл монитора и чистит ресурсы. По умолчанию даётся 10 c; для надёжности можно `docker compose down -t 30`.
- **TLS.** В проде держите `VERIFY_SSL=true` (CA-бандл из `certifi` уже в образе).
- **ffmpeg** входит в образ — нужен `yt-dlp` для видео; отдельно ставить не требуется.
- **Порты не публикуются** — бот работает на long-polling, входящие соединения не нужны.
- **Часовой пояс.** Логи/таймеры используют системное время контейнера (UTC). Чтобы синхронизировать с хостом, можно добавить в сервис `bot` переменную `TZ` и смонтировать `/etc/localtime` (по желанию).
