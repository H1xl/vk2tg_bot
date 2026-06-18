"""
Message templates for bot responses
Шаблоны сообщений для ответов бота
"""


class Messages:
    """Message templates with i18n support placeholder"""

    # =====
    # Common / Shared
    # Общие
    # =====

    NO_NAME = "Без имени"
    UNKNOWN_TITLE = "Без названия"
    SAFE_YES = "да"
    SAFE_NO = "нет"
    PAIR_SAFETY_ON = "включена"
    PAIR_SAFETY_OFF = "отключена (проверка комментариев)"
    CHANNEL_ACCESS_PROBE = "Проверка доступа…"

    # =====
    # Interactive argument prompts
    # Запрос обязательных параметров
    # =====

    ACTION_CANCELLED = "🚫 Действие отменено."

    # =====
    # Menu / button UI
    # Меню / интерфейс кнопок
    # =====

    MENU_OPENED = "🧭 <b>Меню</b>\n\nВыберите действие кнопкой ниже или введите команду вручную.\nСкрыть меню: /hide"
    MENU_HIDDEN = "🙈 Меню скрыто. Открыть снова: /menu"
    PROMPT_PAIR_ID = "❓ Вы не ввели ID пары.\nВведите его или отмените действие: /cancel"
    PROMPT_PAIR_ID_OR_NAME = (
        "❓ Вы не ввели ID или имя пары.\nВведите или отмените действие: /cancel"
    )
    PROMPT_BACKFILL = "❓ Укажите ID пары (и при желании число постов, например <code>pair1 50</code>).\nВведите или отмените: /cancel"
    PROMPT_BROADCAST = "❓ Введите текст уведомления для рассылки.\nИли отмените действие: /cancel"
    PROMPT_USER = (
        "❓ Укажите ID или @username пользователя.\nВведите или отмените действие: /cancel"
    )
    PROMPT_CONNECT = "❓ Пришлите ссылку на VK-группу (и при желании is_safe, имя, pair_id).\nИли отмените действие: /cancel"

    # =====
    # Auth messages
    # Сообщения аутентификации
    # =====

    NOT_AUTHORIZED = "🔐 Вам необходимо авторизоваться.\nИспользуйте команду /login"
    ALREADY_AUTHORIZED = "✅ Вы уже авторизованы!"
    PERMANENT_ADMIN_REQUIRED = "❌ Эта команда доступна только главному администратору"

    LOGIN_PROMPT = "🔑 Введите код приглашения для авторизации:"
    LOGIN_SUCCESS = "✅ Авторизация успешна!\n\nВаша роль: <b>Временный администратор</b>\nСессия действительна 24 часа.\n\nИспользуйте /help для просмотра доступных команд."
    LOGIN_INVALID_CODE = "❌ Неверный или истекший код приглашения.\n\nПопробуйте снова: /login"
    LOGIN_CANCELLED = "🔓 Авторизация отменена"

    # =====
    # Admin commands
    # Команды администратора
    # =====

    INVITE_CODE_GENERATED = "🎫 <b>Код приглашения создан:</b>\n\n<code>{code}</code>\n\n⏰ Действителен: 24 часа\n\n💡 Отправьте этот код пользователю для предоставления временных прав администратора."

    REVOKE_USAGE = "❌ Использование: <code>/revoke [user_id|@username]</code>\n\nПример: <code>/revoke 123456789</code> или <code>/revoke @username</code>"
    REVOKE_SUCCESS = "✅ Права временного администратора отозваны для {user}"
    REVOKE_NOT_TEMP_ADMIN = "❌ Пользователь не является временным администратором"

    BLOCK_USAGE = "❌ Использование: <code>/ban [user_id|@username]</code>\n\nПример: <code>/ban 123456789</code> или <code>/ban @username</code>"
    BLOCK_SUCCESS = "🚫 Пользователь {user} заблокирован"
    CANNOT_BLOCK_ADMIN = "❌ Невозможно заблокировать главного администратора"

    UNBLOCK_USAGE = "❌ Использование: <code>/unban [user_id|@username]</code>\n\nПример: <code>/unban 123456789</code> или <code>/unban @username</code>"
    UNBLOCK_SUCCESS = "✅ Пользователь {user} разблокирован"

    BLOCKLIST_EMPTY = "✅ Список заблокированных пользователей пуст"
    BLOCKLIST_HEADER = "🚫 <b>Заблокированные</b> · {count}"
    BLOCKLIST_CARD_NAMED = "🚫 <b>{username}</b>\n   🆔 <code>{user_id}</code>"
    BLOCKLIST_CARD_ID = "🚫 🆔 <code>{user_id}</code>"

    INVALID_USER_ID = "❌ Неверный формат ID пользователя или username не найден"
    USER_NOT_FOUND = "❌ Пользователь не найден"

    # =====
    # Report system
    # Система репортов
    # =====

    REPORT_BLOCKED = "🚫 Вы заблокированы и не можете отправлять репорты"
    REPORT_RATE_LIMIT = (
        "⏱️ Вы отправили слишком много репортов.\n\nПопробуйте снова через {minutes} минут."
    )
    REPORT_ENTER_REASON = (
        "📝 <b>Шаг 1/2: Опишите проблему</b>\n\nВведите причину жалобы (максимум 500 символов):"
    )
    REPORT_REASON_TOO_LONG = "❌ Текст слишком длинный. Максимум 500 символов."
    REPORT_REASON_TOO_SHORT = "❌ Причина слишком короткая. Минимум 10 символов.\n\nПожалуйста, опишите проблему более подробно."
    REPORT_FORWARD_POST = "📤 <b>Шаг 2/2: Переслать сообщение</b>\n\nТеперь перешлите мне сообщение из канала, на которое вы жалуетесь."
    REPORT_NOT_FROM_CHANNEL = (
        "❌ Пожалуйста, перешлите сообщение из <b>канала</b>, а не из личного чата."
    )
    REPORT_UNKNOWN_CHANNEL = "❌ Этот канал не отслеживается ботом.\n\nИспользуйте /channels для просмотра списка доступных каналов."
    REPORT_USE_CHANNELS_COMMAND = (
        "💡 Используйте команду /channels для просмотра списка каналов, которые отслеживает бот."
    )
    REPORT_SUCCESS = "✅ <b>Репорт отправлен!</b>\n\nСпасибо за обратную связь. Администраторы рассмотрят вашу жалобу."
    REPORT_CANCELLED = "🔓 Отправка репорта отменена"
    REPORT_CHANNEL_NOT_CONFIGURED = (
        "❌ Канал для репортов не настроен.\n\nОбратитесь к администратору бота."
    )
    REPORT_SEND_FAILED = "❌ Произошла ошибка при отправке репорта.\n\nПожалуйста, попробуйте позже или обратитесь к администратору."

    REPORT_TO_CHANNEL = (
        "📢 <b>Новый репорт</b>\n\n"
        "👤 От пользователя: {user_link}\n"
        "📺 Канал: {channel_link}\n"
        "🆔 Pair ID: <code>{pair_id}</code>\n\n"
        "📝 Причина:\n{reason}"
    )

    # =====
    # Channels list
    # Список каналов
    # =====

    CHANNELS_EMPTY = "📋 В данный момент нет активных каналов для мониторинга."
    CHANNELS_HEADER = "📋 <b>Активные каналы</b> · {count}"
    CHANNELS_CARD = "📺 {channel}\n   📨 {posts} за 24ч"
    CHANNELS_PRIVATE_SUFFIX = " 🔒 <i>приватный</i>"
    CHANNELS_RATE_LIMIT = "⏱️ Слишком много запросов.\n\nПожалуйста, подождите {minutes} мин. перед следующим запросом."
    CHANNELS_BLOCKED = "🚫 Вы заблокированы и не можете использовать эту команду."

    # =====
    # Pair management
    # Управление парами
    # =====

    PAIR_USAGE = '❌ Использование: <code>/connect &lt;vk_id|link&gt; [is_safe] [name] [pair_id]</code>\n\nПример: <code>/connect https://vk.com/apiclub false "Tech News" tech_1</code>'
    PAIR_INVALID_IS_SAFE = "❌ Неверное значение is_safe. Используйте: true, false, 1, 0, yes, no"
    PAIR_NAME_TOO_LONG = "❌ Имя пары слишком длинное (максимум 100 символов)."
    PAIR_INVALID_ID_FORMAT = (
        "❌ Неверный формат pair_id. Используйте буквы, цифры и подчеркивания (до 50 символов)."
    )
    PAIR_INVALID_VK_ID = "❌ Неверный формат VK ID или ссылки."
    PAIR_VK_GROUP_FETCH = "⏳ Получаю информацию о группе VK..."
    PAIR_VK_GROUP_NOT_FOUND = (
        "❌ Не удалось получить ID группы VK. Проверьте правильность ссылки или ID."
    )
    PAIR_VK_ACCESS_CHECK = "⏳ Проверяю доступ к группе VK..."
    PAIR_VK_NO_ACCESS = "❌ Нет доступа к группе VK. Проверьте, что группа публичная и доступна."
    PAIR_VERIFICATION_PROMPT = "🔐 <b>Верификация канала</b>\n\nШаг 1: Добавьте бота в ваш канал администратором\n\nШаг 2: Опубликуйте этот код в вашем канале:\n<code>{code}</code>\n\nШаг 3: Перешлите сообщение с кодом мне\n\n⏱️ У вас есть {timeout} минут\n🚫 Отменить создание пары: /cancel"
    PAIR_VK_ALREADY_CONNECTED = "❌ Эта VK-группа уже подключена к паре <code>{pair_id}</code>.\n\nОдну группу нельзя подключить дважды. Удалите существующую пару (<code>/delete {pair_id}</code>) или используйте другую группу."
    PAIR_VERIFICATION_NOT_FOUND = (
        "❌ Верификация не найдена. Используйте <code>/connect</code> для начала."
    )
    PAIR_FORWARD_FROM_CHANNEL_ONLY = (
        "❌ Пожалуйста, перешлите сообщение <b>из канала</b>, а не из личного чата."
    )
    PAIR_CODE_NOT_FOUND = "❌ Код не найден в сообщении.\nОжидаемый код: <code>{code}</code>"
    PAIR_CHANNEL_ACCESS_CHECK = "⏳ Проверяю доступ к каналу {title}..."
    PAIR_NO_CHANNEL_ACCESS = "❌ Не могу отправлять сообщения в канал.\n\nУбедитесь, что:\n• Бот добавлен в канал\n• Бот имеет права администратора\n• Бот может публиковать сообщения"
    PAIR_CREATED = """✅ <b>Канал подключён</b>

🔗 <b>{title}</b>
🆔 <code>{pair_id}</code>
🏷️ {name}
{safety}
🔴 Статус: остановлено

▶️ Запустить пересылку: /enable
<i>(затем введите ID пары — он выше)</i>"""
    PAIR_ALREADY_EXISTS = "❌ {error}"
    PAIR_EXISTS_ERROR = "Пара с ID '{pair_id}' уже существует"
    PAIR_CREATION_ERROR = "❌ Ошибка при создании пары: <code>{error}</code>"
    PAIR_COMMAND_PARSE_ERROR = "❌ Ошибка парсинга команды: {error}\n\nИспользуйте правильные кавычки для аргументов с пробелами."
    PAIR_CREATION_CANCELLED = "🔓 Создание пары отменено"

    PAIR_NOT_FOUND = "❌ Пара <code>{pair_id}</code> не найдена."
    PAIR_ACTIVATED = "✅ Пара <code>{pair_id}</code> активирована!"
    PAIR_STOPPED = "⏹️ Пара <code>{pair_id}</code> остановлена!"
    PAIR_REMOVED = "✅ Пара <code>{pair_id}</code> успешно удалена!"
    PAIR_REMOVE_FAILED = "❌ Не удалось удалить пару."

    PAIR_REMOVE_USAGE = "❌ Использование: <code>/delete &lt;pair_id|name&gt;</code>\n\nПример: <code>/delete pair1</code>"
    PAIR_ACTIVATE_USAGE = "❌ Использование: <code>/enable &lt;pair_id&gt;</code>\n\nПример: <code>/enable pair1</code>"
    PAIR_STOP_USAGE = "❌ Использование: <code>/disable &lt;pair_id&gt;</code>\n\nПример: <code>/disable pair1</code>"

    # =====
    # List command
    # Команда списка
    # =====

    LIST_EMPTY = "📋 Пары не найдены.\n\nИспользуйте <code>/connect</code> для создания новой пары."
    LIST_HEADER = "🗂️ <b>Список пар</b> · стр. {page}/{total_pages}"
    LIST_CARD = "{status} <b>{name}</b>\n   VK <code>{vk_id}</code> · {safety}\n   🆔 <code>{pair_id}</code>"
    PAIR_STATUS_ACTIVE = "🟢"
    PAIR_STATUS_STOPPED = "🔴"
    PAIR_SAFE_TRUSTED = "🛡 безопасный"
    PAIR_SAFE_CHECKED = "🔎 проверка рекл."
    LIST_NAVIGATION = "💡 Навигация: "
    LIST_MORE_ERRORS = "\n... и ещё {count} ошибок"

    # =====
    # Actions
    # Действия
    # =====

    FILL_USAGE = "❌ Использование: <code>/backfill &lt;pair_id&gt; [количество]</code>\n\nПо умолчанию: 100 постов\n\nПример: <code>/backfill pair1 50</code>"
    FILL_INVALID_COUNT = (
        "❌ Неверное значение количества: <code>{value}</code>\nДолжно быть число от 1 до 100."
    )
    FILL_COUNT_RANGE = "❌ Количество постов должно быть от 1 до 100."
    FILL_PAIR_NOT_FOUND = "❌ Пара <code>{pair_id}</code> не найдена."
    FILL_STARTED = "⏳ Начинаю пересылку {count} постов для пары <code>{pair_id}</code>..."
    FILL_NO_POSTS = "❌ Не удалось получить посты из VK."
    FILL_NO_POSTS_AFTER_FILTER = "❌ Нет постов для пересылки после фильтрации."
    FILL_PROGRESS = """⏳ <b>Обработка постов</b>

<code>{progress_bar}</code>

✅ Успешно: <b>{success}</b>
⏭️ Пропущено: <b>{skipped_ads}</b>
❌ Ошибки: <b>{errors}</b>
📊 {current}/{total} ({percent}%)"""
    FILL_COMPLETE = """✅ <b>Пересылка завершена</b>

📨 Всего постов: <b>{total}</b>
✅ Успешно: <b>{success}</b>
⏭️ Пропущено: <b>{skipped_ads}</b>
❌ Ошибки: <b>{errors}</b>"""
    FILL_ERRORS_DETAIL = "\n\n⚠️ Детали ошибок:\n"
    FILL_ERROR_ITEM = "• Пост {post_id}: {url}"
    FILL_ERROR = "❌ Произошла ошибка:\n<code>{error}</code>"

    NOTICE_USAGE = "❌ Использование: <code>/broadcast &lt;текст&gt;</code>\n\nПример: <code>/broadcast Техническое обслуживание через 1 час</code>\n\nСообщение будет отправлено во все активные каналы."
    NOTICE_TOO_LONG = "❌ Текст слишком длинный. Максимум 4096 символов."
    NOTICE_NO_ACTIVE_PAIRS = "⚠️ Нет активных пар для рассылки."
    NOTICE_STARTED = "📢 <b>Рассылка</b> в {count} канал(ов)…\n\n💬 Текст:\n{text}"
    NOTICE_PROGRESS = """📢 <b>Рассылка уведомления</b>

<code>{progress_bar}</code>

✅ Успешно: <b>{success}</b>
❌ Ошибки: <b>{errors}</b>
📊 {current}/{total} ({percent}%)"""
    NOTICE_COMPLETE = """✅ <b>Рассылка завершена</b>

📡 Всего каналов: <b>{total}</b>
✅ Успешно: <b>{success}</b>
❌ Ошибки: <b>{errors}</b>"""
    NOTICE_BROADCAST = "📢 Уведомление:\n{text}"

    # =====
    # Avatar update
    # Обновление аватарки
    # =====

    UPDATE_USAGE = "❌ Использование: <code>/avatar &lt;pair_id&gt;</code>\n\nПример: <code>/avatar pair1</code>"
    UPDATE_PAIR_NOT_FOUND = "❌ Пара <code>{pair_id}</code> не найдена."
    UPDATE_STARTED = "⏳ Обновляю аватарку для пары <code>{pair_id}</code>..."
    UPDATE_SUCCESS = "✅ Аватарка канала успешно обновлена!"
    UPDATE_NO_CHANGE = "ℹ️ Аватарка не изменилась с последнего обновления."
    UPDATE_VK_FETCH_FAILED = "❌ Не удалось получить аватарку из VK."
    UPDATE_DOWNLOAD_FAILED = "❌ Не удалось скачать аватарку."
    UPDATE_TG_UPDATE_FAILED = "❌ Не удалось обновить аватарку канала в Telegram.\n\nУбедитесь, что бот имеет права администратора."
    UPDATE_ERROR = "❌ Произошла ошибка при обновлении аватарки:\n<code>{error}</code>"

    AVATAR_UPDATED_NOTIFICATION = "🖼️ Аватарка канала обновлена"

    # =====
    # Post forwarding messages
    # Сообщения пересылки постов
    # =====

    VIDEO_LINKS_HEADER = "Видео доступно по ссылкам:\n\n"
    AUDIO_UNAVAILABLE = "Аудио: {artist} - {title}"
    AUDIO_WITH_LINK = "Аудио: {artist} - {title}\n{url}"
    DOCUMENT_UNAVAILABLE = "{doc_type}: {title}\n{url}"

    # Article / Статья
    ARTICLE_DEFAULT_TITLE = "Статья"
    ARTICLE_TITLE = "🗞️ {title}"
    ARTICLE_READ_LINK = "\n\nЧитать статью: {url}"

    # Playlist / Плейлист
    PLAYLIST_DEFAULT_TITLE = "Плейлист"
    PLAYLIST_INFO = "🎵 <b>{title}</b>\n\nТреков: {count}\nСсылка: {url}"

    # =====
    # System
    # Система
    # =====

    GENERIC_ERROR = "❌ Произошла ошибка при обработке команды. Попробуйте позже."
    DATABASE_ERROR = "❌ Ошибка базы данных. Попробуйте позже."
    NETWORK_ERROR = "❌ Ошибка сети. Проверьте подключение и попробуйте снова."
    PERMISSION_ERROR = "❌ Недостаточно прав для выполнения операции."
    VALIDATION_ERROR = "❌ Неверные данные. Проверьте введённую информацию."
    TIMEOUT_ERROR = "⏱️ Превышено время ожидания операции. Попробуйте позже."

    START_MESSAGE = (
        "👋 <b>Бот пересылки постов из VK в Telegram</b>\n\n"
        "Доступно всем:\n"
        "• 🧭 /menu — меню с кнопками\n"
        "• 📋 /channels — список активных каналов\n"
        "• ⚠️ /report — пожаловаться на пост\n\n"
        "💡 Нажмите кнопку <b>Menu</b> слева от поля ввода, чтобы выбрать команду."
    )

    HELP_MESSAGE = """📋 <b>Доступные команды</b>
<i>(в скобках — короткие варианты)</i>

<b>Авторизация:</b>
<code>/login</code> — аутентификация в боте

<b>Управление парами:</b>
<code>/connect &lt;vk_id|link&gt; [is_safe] [name] [pair_id]</code> (<code>/con</code>)
  Подключить VK-группу к Telegram-каналу с проверкой
  Порядок: ссылка VK (обязательно), is_safe (опц., по умолч. false), имя (опц.), pair_id (опц.)
  • true — без проверки комментариев
  • false — проверять первые 5 комментариев на рекламу
  Пример: <code>/connect https://vk.com/apiclub false "Tech News" tech_1</code>

<code>/pairs [page]</code> (<code>/ls</code>) — список всех пар
<code>/enable &lt;pair_id&gt;</code> (<code>/on</code>) — запустить пересылку
<code>/disable &lt;pair_id&gt;</code> (<code>/off</code>) — остановить пересылку
<code>/delete &lt;pair_id|name&gt;</code> (<code>/del</code>) — удалить пару полностью
<code>/avatar &lt;pair_id&gt;</code> (<code>/av</code>) — обновить аватарку канала из VK

<b>Действия:</b>
<code>/backfill &lt;pair_id&gt; [count]</code> (<code>/bf</code>) — переслать последние N постов (по умолч. 100)
<code>/broadcast &lt;text&gt;</code> (<code>/bc</code>) — отправить сообщение во все активные каналы

<b>Для пользователей:</b>
<code>/channels</code> (<code>/ch</code>) — список активных каналов
<code>/report</code> (<code>/rep</code>) — отправить жалобу на пост

<b>Система:</b>
<code>/menu</code> (<code>/m</code>) — меню с кнопками управления
<code>/status</code> (<code>/st</code>) — статус системы
<code>/errors</code> (<code>/err</code>) — последние ошибки
<code>/logs</code> (<code>/log</code>) — файл логов
<code>/help</code> (<code>/h</code>) — эта справка

<b>Администрирование (только главный админ):</b>
<code>/invite</code> (<code>/inv</code>) — создать код приглашения временного админа
<code>/revoke &lt;user_id|@username&gt;</code> (<code>/rev</code>) — отозвать права временного админа
<code>/ban &lt;user_id|@username&gt;</code> — заблокировать пользователя (репорты)
<code>/unban &lt;user_id|@username&gt;</code> — разблокировать пользователя
<code>/banned</code> (<code>/bans</code>) — список заблокированных"""

    STATUS_MESSAGE = """📊 <b>Статус системы</b>

📦 Пар всего: <b>{total_pairs}</b>
🟢 Активных: <b>{active_pairs}</b>
🕐 Последний цикл: <b>{last_cycle}</b>

⚠️ Ошибок за 24ч: <b>{errors_24h}</b>
⚡ Среднее время: <b>{avg_time:.2f} c</b>
📨 Переслано всего: <b>{total_posts}</b>"""

    ERRORS_NONE = "✅ Ошибок не обнаружено!"
    ERRORS_HEADER = "⚠️ <b>Ошибки за 24ч: {count}</b>\nПоследние {shown}:"

    LOGS_NOT_FOUND = "❌ Файл логов не найден."
    LOGS_SEND_FAILED = "❌ Не удалось отправить файл логов."
    LOGS_CAPTION = "📄 Файл логов"

    # =====
    # Monitor messages
    # Сообщения монитора
    # =====

    MONITOR_FORWARD_FAILED = "Не удалось отправить пост после {attempts} попыток"

    MONITOR_PAIR_STOPPED_NOTIFICATION = (
        "⚠️ <b>КРИТИЧЕСКАЯ ОШИБКА</b>\n\n"
        "Пара <code>{pair_id}</code> ({pair_name}) остановлена после множественных ошибок отправки.\n\n"
        "🔗 Проблемный пост: https://vk.com/wall-{vk_id}_{post_id}\n"
        "❌ Ошибка: {error_message}\n"
        "🔄 Попыток: {attempts}\n\n"
        "Пара автоматически остановлена. Для возобновления отправьте /enable и введите ID <code>{pair_id}</code>."
    )

    # =====
    # Auth service messages
    # Сообщения сервиса аутентификации
    # =====

    SESSION_EXPIRED = "⏱️ Ваша администраторская сессия истекла"
    TEMP_ADMIN_NOTIFICATION = (
        "🔑 <b>Новый временный администратор</b>\n\n"
        "👤 Пользователь: {user_mention}\n"
        "🆔 ID: <code>{user_id}</code>\n"
        "🎫 Код: <code>{code}</code>\n"
        "⏰ Действителен до: {expires_str}"
    )
    TEMP_ADMIN_REVOKED = "🔓 Ваши права администратора были отозваны"
