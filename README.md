# MAX2TG-Bridge

> Двусторонний мост между мессенджером **MAX** (`web.max.ru` / `api.oneme.ru`) и **Telegram** через форум-топики в супергруппе.

Проект развивает [ircitdev/MAX2TG-Bridge](https://github.com/ircitdev/MAX2TG-Bridge) и сохраняет благодарность первоисточнику и его авторам.

> Проект полностью переведён на [PyMax](https://github.com/MaxApiTeam/PyMax). Старый собственный WebSocket-клиент и его переменные окружения больше не поддерживаются.

Каждый чат MAX становится отдельным форум-топиком в твоей супергруппе Telegram. Входящие сообщения из MAX (текст, фото, файлы, видео, голосовые, стикеры, контакты, локации, цитаты, пересланные) приходят в свой топик. Ответ написанный в этом топике уходит обратно собеседнику в MAX от твоего имени.

При создании топика автоматически постится и закрепляется карточка собеседника с именем, id и аватаром.

<p align="center">
  <img src="docs/infographic.png" alt="Как работает MAX2TG-Bridge" width="720"/>
</p>

---

## Содержание

- [Возможности](#возможности)
- [Архитектура](#архитектура)
- [Требования](#требования)
- [Установка](#установка)
- [Конфигурация](#конфигурация-env)
- [Команды бота](#команды-бота)
- [Известные ограничения](#известные-ограничения)
- [Разработка](#разработка)
- [Disclaimer](#disclaimer)
- [Лицензия](#лицензия)

---

## Возможности

### MAX → Telegram
- Текст с сохранением форматирования (жирный / курсив / зачёркнутый / подчёркнутый / моноширинный / цитата / ссылки)
- Фото и видео с подписью; вложения одного сообщения объединяются в Telegram-альбом
- Полное скачивание нативных видео через PyMax с fallback на превью или текстовую пометку
- Документы любых типов
- Голосовые и аудио (когда MAX отдаёт `_type=AUDIO`; для нового `_type=UNSUPPORTED` пока fallback на «не удалось скачать»)
- Стикеры
- Контакты, локации, ссылки-превью
- Пересланные сообщения и цитаты с подписью отправителя
- Текстовая пометка о типе вложения, если медиа не удалось скачать или отправить
- Уведомления о статусе подключения к MAX в General-топик (с троттлингом)

### Telegram → MAX
- Текст (пока без переноса Telegram entities)
- Фото через нативную загрузку MAX
- Видео через нативный `Video` в PyMax; документы и обычное аудио — как файлы
- Нативные голосовые сообщения через `pymax.Voice` с сохранением длительности
- Telegram-альбомы собираются по `media_group_id` и отправляются одним сообщением MAX
- Реакция 👀 на успешную доставку, текст ошибки от MAX — на провал

### Управление
- Авто-создание форум-топика на каждый новый чат MAX
- Закреплённая карточка профиля при создании топика
- Команды: `/bind`, `/add`, `/profile`, `/intro`, `/del`, `/help`
- Опциональный список пользователей, которым разрешено отвечать (`TG_ALLOWED_USER_IDS`)
- SOCKS5-прокси для Telegram (`TG_PROXY`)
- Карта связок переживает рестарт (`state/topics.json`)
- Авто-переподключение к MAX и алёрт при обрыве

---

## Архитектура

```
  ┌────────────────┐    WebSocket    ┌──────────────────┐
  │ API MAX        │  ◄────────────► │   max2tg (app)   │
  │ через PyMax    │                 │  ├ PyMaxClient   │
  └────────────────┘                 │  ├ Resolver      │
                                     │  ├ TelegramSender│
  ┌────────────────┐    Bot API      │  └ tg_handler    │
  │ api.telegram.  │  ◄────────────► │                  │
  │ org            │                 │  state/topics.json│
  └────────────────┘                 └──────────────────┘
```

- `app/main.py` — точка входа: загружает `.env`, поднимает PyMax и Telegram Application (polling), привязывает их через TopicStore.
- `app/pymax_client.py` — единый клиент MAX: события, чаты, контакты, загрузка и скачивание медиа.
- `app/max_listener.py` — приём сообщений из MAX, маршрутизация в Telegram-топики, авто-создание топиков, постинг карточки.
- `app/resolver.py` — кеш контактов и чатов MAX.
- `app/tg_sender.py` — отправка в Telegram, `ensure_topic` (создание форум-топиков, переименование при появлении настоящего имени).
- `app/tg_handler.py` — команды и медиа из Telegram → MAX.
- `app/topics.py` — `TopicStore`: атомарно-сохраняемая JSON-карта `max_chat_id ↔ telegram_thread_id`.

---

## Требования

- Python **3.12+** (для локального запуска)
- Docker + docker-compose v2 (для рекомендуемого деплоя)
- Аккаунт MAX (`web.max.ru`)
- Супергруппа Telegram с **включёнными темами** (Topics / Forum)
- Telegram-бот (через [@BotFather](https://t.me/BotFather)) — администратор супергруппы с правом «**Управление темами**»

---

## Установка

### 1. Подготовка Telegram

1. Создай супергруппу и в её настройках включи **«Темы» / «Topics»**.
2. У [@BotFather](https://t.me/BotFather) сделай нового бота → запиши **`TG_BOT_TOKEN`**.
3. Добавь бота в супергруппу администратором, поставь галку «Управление темами» (без этого права бот не сможет создавать топики).
4. Получи **`TG_CHAT_ID`** супергруппы: перешли любое сообщение из неё боту [@userinfobot](https://t.me/userinfobot) — он покажет id вида `-100…`.
5. (Опционально) Telegram user ID разрешённых пользователей — для `TG_ALLOWED_USER_IDS` (через запятую; ID покажет @userinfobot в личке).
6. В настройках реакций супергруппы разреши «**Все эмодзи**», чтобы бот мог ставить 👀 на отправленные ответы.

### 2. Авторизация MAX

Проект использует только PyMax. По умолчанию применяется QR-вход:

```env
MAX_PYMAX_AUTH=qr
```

При первом запуске открой ссылку `PyMax QR authorization URL` из логов и подтверди вход в MAX. Если включена 2FA, интерактивный запуск дополнительно запросит пароль. Сессия сохранится в `state/pymax/pymax-qr.db`, поэтому каталог `state` нельзя удалять.

PyMax поддерживает два flow авторизации:

- `MAX_PYMAX_AUTH=sms` — TCP `Client`, первичный вход по `MAX_PHONE` и SMS-коду.
- `MAX_PYMAX_AUTH=qr` — WebSocket `WebClient`, первичный вход по QR; ссылка пишется в лог.

### 3. Деплой (Docker, рекомендованный)

```bash
git clone https://github.com/Maks113/MAX2TG-Bridge.git max2tg
cd max2tg
cp .env.example .env
# отредактируйте .env
docker compose up -d --build
docker compose logs -f
```

Готово. Бот в General-топике супергруппы пришлёт `✅ Max: подключён | чатов: N`. При первом входящем сообщении из MAX автоматически создастся топик.

Готовый образ публикуется для `linux/amd64` и `linux/arm64` при создании GitHub Release:

```bash
docker pull ghcr.io/maks113/max2tg-bridge:latest
```

Для обновления установленного через Compose экземпляра:

```bash
docker compose pull
docker compose up -d
```

Том `./state` хранит карту `max_chat_id ↔ thread_id` (`state/topics.json`) — не теряй его, иначе при следующих сообщениях создадутся дубли топиков.
Там же хранится SQLite-сессия PyMax; её потеря потребует повторной QR/SMS-авторизации.

### 4. Локальный запуск (для разработки)

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env  # отредактировать
python -m app.main
```

### 5. systemd (Linux)

`/etc/systemd/system/max2tg.service`:
```ini
[Unit]
Description=MAX2TG-Bridge
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/max2tg
ExecStart=/opt/max2tg/.venv/bin/python -m app.main
EnvironmentFile=/opt/max2tg/.env
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now max2tg
sudo journalctl -u max2tg -f
```

---

## Конфигурация `.env`

| Переменная | Обязательная | Описание |
|---|---|---|
| `MAX_PYMAX_AUTH` | нет | `qr` (по умолчанию) или `sms` |
| `MAX_PHONE` | для `sms` | Номер телефона для первичной SMS-авторизации PyMax |
| `MAX_2FA_PASSWORD` | нет | Пароль 2FA для PyMax SMS-авторизации, если включён на аккаунте |
| `MAX_PYMAX_WORK_DIR` | нет | Папка SQLite-сессии PyMax, по умолчанию `STATE_DIR/pymax` |
| `MAX_PYMAX_SESSION_NAME` | нет | Имя файла сессии PyMax, по умолчанию `pymax-sms.db` или `pymax-qr.db` |
| `TG_BOT_TOKEN` | да | Токен бота от @BotFather |
| `TG_CHAT_ID` | да | ID супергруппы (отрицательное число вида `-100…`) |
| `TG_ALLOWED_USER_IDS` | нет | Telegram user ID через запятую — ограничивают, кто может слать команды и ответы |
| `MAX_CHAT_IDS` | нет | Список chat_id MAX через запятую — если задан, обрабатываются только эти чаты |
| `TG_PROXY` | нет | SOCKS5-прокси для Telegram, формат `socks5://[user:pass@]host:port` |
| `STATE_DIR` | нет | Папка для `topics.json` (по умолчанию `state`) |
| `REPLY_ENABLED` | нет | `true` — включить ответы из топиков в MAX |
| `DEBUG` | нет | `true` — verbose-логи |
| `DEBUG_DUMP_JSON` | нет | `true` — сохранять redacted JSON в `debug/`; может содержать текст сообщений |
| `MAX_DOWNLOAD_MB` | нет | Максимальный размер вложения из MAX для скачивания в память, по умолчанию `50` |
| `TG_UPLOAD_MB` | нет | Максимальный размер файла из Telegram для отправки в MAX, по умолчанию `50` |

---

## Команды бота

Все команды работают только в супергруппе (`TG_CHAT_ID`). При `TG_ALLOWED_USER_IDS` — только от перечисленных пользователей.

| Команда | Что делает |
|---|---|
| `/bind <chat_id или URL> [название]` | Создать топик под конкретный чат MAX. URL вида `https://web.max.ru/<chat_id>` тоже принимается. |
| `/add <https://max.ru/join/...>` | Открыть групповую/канальную ссылку MAX, создать топик и поставить карточку. |
| `/profile` | (в топике) Показать профиль собеседника MAX: имя, id, аватар. |
| `/intro` | (в топике) Перепостить и закрепить карточку профиля. |
| `/del` | (в топике) Удалить топик и снять связь с MAX-чатом (с подтверждением). |
| `/help` | Список всех команд. |

---

## Известные ограничения

1. **Голосовые MAX → TG** могут приходить без доступного URL. В таком случае мост отправляет текстовую пометку вместо потери сообщения.
2. **Ссылки `/u/<token>`** могут не открываться через `/add`. Workaround: открыть ссылку в MAX; авто-топик создастся при первом сообщении.
3. **Лимиты Telegram Bot API** и значения `MAX_DOWNLOAD_MB`/`TG_UPLOAD_MB` ограничивают размер передаваемых файлов.
4. **Кастомные эмодзи как реакции** — Telegram запрещает ботам ставить custom-emoji реакции, поэтому используется обычная `👀`.
5. **Phone / about** в `/profile` могут отсутствовать, если MAX не вернул эти поля.
6. **Форматирование Telegram → MAX** пока отправляется как plain text: публичный PyMax API не принимает Telegram entities напрямую.

---

## Разработка

### Тесты

```bash
pip install pytest pytest-asyncio
pytest -q
```

Покрытие: TopicStore, конфигурация, маршрутизация, группировка и fallback медиа, PyMax auth и единый PyMax-клиент. 145 тестов.

### Структура проекта

```
max2tg/
├── app/
│   ├── main.py             # точка входа
│   ├── config.py           # загрузка .env
│   ├── pymax_auth.py       # PyMax Client/WebClient auth factory
│   ├── pymax_client.py     # единый клиент MAX на PyMax
│   ├── max_listener.py     # MAX → TG роутинг + backend wiring
│   ├── resolver.py         # кеш контактов / чатов
│   ├── tg_sender.py        # TG отправка + ensure_topic
│   ├── tg_handler.py       # TG → MAX роутинг и команды
│   └── topics.py           # TopicStore (JSON-карта)
├── tests/                  # 145 pytest
├── state/                  # рантайм-данные (gitignored)
├── logs/                   # логи (gitignored)
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── AGENTS.md               # контекст для AI-ассистентов
└── README.md
```

---

## Disclaimer

1. Проект **независимый, неофициальный**, не связан с разработчиками MAX (VK Group) или Telegram (TG Messenger Inc.).
2. Использует неофициальный клиент PyMax. Внутренний протокол MAX может измениться без предупреждения — мост может перестать работать.
3. Работает как **userbot** к твоему MAX-аккаунту — есть формальный риск блокировки по правилам сервиса. Используй на свой страх и риск.
4. Программа предоставляется **«как есть»**, без гарантий.

---

## Лицензия

[MIT](LICENSE). Этот репозиторий основан на [ircitdev/MAX2TG-Bridge](https://github.com/ircitdev/MAX2TG-Bridge), который, в свою очередь, развивает идеи [Aist/max2tg](https://github.com/Aist/max2tg).
Большое спасибо [nsdkinx/vkmax](https://github.com/nsdkinx/vkmax), [max-messenger/max-botapi-python](https://github.com/max-messenger/max-botapi-python) и [PyMax](https://docs.pymax.org/) за документацию, enum'ы и клиентскую библиотеку.
