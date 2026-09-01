# MAX2TG-Bridge — контекст для AI-ассистентов

## Назначение

Двусторонний мост MAX ↔ Telegram через форум-топики супергруппы. Каждый MAX-чат соответствует отдельному Telegram topic. Репозиторий полностью переведён на PyMax; собственного WebSocket-клиента больше нет.

Проект основан на [ircitdev/MAX2TG-Bridge](https://github.com/ircitdev/MAX2TG-Bridge), который развивает [Aist/max2tg](https://github.com/Aist/max2tg). Лицензия MIT.

## Структура

- `app/main.py` — запуск PyMax и Telegram polling.
- `app/config.py` — конфигурация окружения; QR является auth-flow по умолчанию.
- `app/pymax_auth.py` — фабрика `pymax.Client`/`WebClient`.
- `app/pymax_client.py` — единый клиент MAX: события, чаты, контакты, медиа и безопасное скачивание.
- `app/max_listener.py` — MAX → Telegram, альбомы, fallback вложений и уведомления reconnect.
- `app/tg_handler.py` — Telegram → MAX, команды, буферизация альбомов и нативные PyMax attachments.
- `app/tg_sender.py` — Telegram Bot API, топики, media groups, retry и увеличенные timeout.
- `app/resolver.py` — кеш чатов и контактов.
- `app/topics.py` — постоянная карта MAX chat ID ↔ Telegram thread ID.

## PyMax

Переменные: `MAX_PYMAX_AUTH=qr|sms`, `MAX_PHONE` для SMS, опциональные `MAX_2FA_PASSWORD`, `MAX_PYMAX_WORK_DIR`, `MAX_PYMAX_SESSION_NAME`. Сессия находится в `state/pymax` и должна сохраняться между рестартами.

Используются нативные `Photo`, `Video`, `Voice` и `File`. Telegram-альбом собирается по `media_group_id` и отправляется одним сообщением MAX. MAX-вложения группируются в Telegram media group до 10 элементов. Чаты из `MAX_CHAT_IDS`, отсутствующие в incremental sync, догружаются через PyMax.

Текст Telegram → MAX пока plain text: публичный `pymax.send_message()` не принимает старые entities напрямую.

## Runtime

- `state/topics.json` — карта топиков, не удалять.
- `state/pymax/*.db` — авторизованная PyMax-сессия, не удалять.
- `logs/max2tg.log` — rotating log.
- Контейнер запускается через `docker compose up -d --build`.

## Тесты

`pytest -q` → 145 passed на момент удаления старого клиента. Покрываются config, topics, resolver, PyMax auth/client, маршрутизация, медиа, альбомы и reconnect.

## Известные ограничения

- Некоторые входящие voice attachments MAX не содержат доступного URL; мост отправляет fallback-текст.
- `/u/<token>` может не открываться через `/add`.
- Phone/about могут отсутствовать в ответах MAX.
- PyMax использует неофициальный внутренний API MAX и может ломаться при изменениях протокола.
