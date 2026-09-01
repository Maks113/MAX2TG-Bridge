import asyncio
import logging
from datetime import datetime
from html import escape

from app.config import Settings
from app.pymax_client import MaxMessage, PyMaxClient
from app.resolver import ContactResolver
from app.tg_sender import TelegramSender

log = logging.getLogger(__name__)

PHOTO_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}

ATTACHMENT_LABELS = {
    "PHOTO": "📷 <i>[фото — не удалось загрузить]</i>",
    "VIDEO": "🎬 <i>[видео — не удалось загрузить]</i>",
    "FILE": "📎 <i>[файл — не удалось загрузить]</i>",
    "AUDIO": "🎵 <i>[аудио — не удалось загрузить]</i>",
    "STICKER": "🏷 <i>[стикер — не удалось загрузить]</i>",
    "LOCATION": "📍 <i>[геолокация — не удалось загрузить]</i>",
    "CONTACT": "👤 <i>[контакт — не удалось загрузить]</i>",
    "SHARE": "🔗 <i>[ссылка — не удалось загрузить]</i>",
}


def _attachment_failure(attach: dict) -> str:
    atype = attach.get("_type", "")
    if atype == "UNSUPPORTED" and attach.get("audioId") is not None:
        return "🎙 <i>[голосовое сообщение — не удалось загрузить]</i>"
    return ATTACHMENT_LABELS.get(
        atype,
        f"📎 <i>[вложение {escape(atype or 'неизвестного типа')} — не удалось загрузить]</i>",
    )


def _header(msg: MaxMessage, sender_label: str, chat_label: str, is_dm: bool) -> str:
    if is_dm:
        return f"✉ <b>{sender_label}</b>"
    return f"💬 <b>{chat_label}</b> | {sender_label}"


def _extract_photo_url(attach: dict) -> str | None:
    """Extract the best available URL for a PHOTO attachment."""
    return attach.get("baseUrl") or attach.get("url")


def _extract_file_url(attach: dict) -> str | None:
    """Extract download URL for a FILE attachment (url field takes priority)."""
    url = attach.get("url")
    if url and url.startswith("http"):
        return url
    return None


def _guess_media_kind(filename: str) -> str:
    name_lower = filename.lower()
    for ext in PHOTO_EXTENSIONS:
        if name_lower.endswith(ext):
            return "photo"
    for ext in VIDEO_EXTENSIONS:
        if name_lower.endswith(ext):
            return "video"
    return "document"


async def _try_send_media_group(
    attaches: list[dict],
    client: PyMaxClient,
    sender: TelegramSender,
    caption: str,
    thread_id: int | None,
    msg: MaxMessage,
) -> bool | None:
    """Group compatible MAX attachments. None means fall back to single sends."""
    if len(attaches) < 2:
        return None

    types = {attach.get("_type") for attach in attaches}
    if types <= {"PHOTO", "VIDEO"}:
        items: list[tuple[str, bytes, str]] = []
        for index, attach in enumerate(attaches):
            if attach.get("_type") == "PHOTO":
                url = _extract_photo_url(attach)
                data = await client.download_file(url) if url else None
                if not data:
                    return None
                items.append(("photo", data, f"photo-{index + 1}.jpg"))
            else:
                video_id = attach.get("videoId")
                if video_id is None:
                    return None
                url = await client.download_video_url(
                    video_id, chat_id=msg.chat_id, message_id=msg.message_id
                )
                data = await client.download_file(url) if url else None
                if not data:
                    return None
                items.append(("video", data, f"{video_id}.mp4"))
        return await sender.send_media_group(
            items, caption=caption, message_thread_id=thread_id
        )

    if types == {"FILE"}:
        items = []
        for attach in attaches:
            name = attach.get("name") or "file"
            url = _extract_file_url(attach)
            if not url and attach.get("fileId") is not None:
                url = await client.resolve_file_url(
                    msg.chat_id, msg.message_id, attach["fileId"]
                )
            data = await client.download_file(url) if url else None
            if not data:
                return None
            items.append(("document", data, name))
        return await sender.send_media_group(
            items, caption=caption, message_thread_id=thread_id
        )

    return None


async def _send_attach(
    attach: dict,
    client: PyMaxClient,
    sender: TelegramSender,
    header_text: str,
    thread_id: int | None = None,
    msg: MaxMessage | None = None,
) -> bool:
    """Process and send a single attachment. Returns True if handled."""
    atype = attach.get("_type", "")
    log.info("Processing attach _type=%s keys=%s", atype, list(attach.keys()))

    if atype == "CONTROL" or atype == "WIDGET" or atype == "INLINE_KEYBOARD":
        return False

    # MAX's newer client sends voice messages with `_type=UNSUPPORTED` plus an
    # `audioId` + `token` (our ver=11 client doesn't speak its native AUDIO
    # variant). Treat this shape as audio.
    if atype == "UNSUPPORTED" and attach.get("audioId") is not None:
        audio_id = attach.get("audioId")
        token = attach.get("token")
        duration = attach.get("duration", 0)
        chat_id = msg.chat_id if msg else None
        message_id = msg.message_id if msg else None
        url = None
        if chat_id is not None and message_id:
            url = await client.download_audio_url(
                audio_id, chat_id, message_id, token=token,
            )
        if url:
            data = await client.download_file(url)
            if data:
                if await sender.send_voice(
                    data, caption=header_text, message_thread_id=thread_id
                ):
                    return True
        dur_s = f" ({duration // 1000}с)" if duration else ""
        await sender.send(
            f"{header_text}\n🎙 <i>[голосовое сообщение{dur_s} — не удалось скачать]</i>",
            message_thread_id=thread_id,
        )
        return True

    if atype == "PHOTO":
        url = _extract_photo_url(attach)
        if not url:
            log.warning("PHOTO attach has no URL: %s", attach)
            await sender.send(
                f"{header_text}\n{_attachment_failure(attach)}",
                message_thread_id=thread_id,
            )
            return True
        data = await client.download_file(url)
        if data:
            if await sender.send_photo(
                data, caption=header_text, message_thread_id=thread_id
            ):
                return True
        await sender.send(f"{header_text}\n<i>[фото — не удалось загрузить]</i>", message_thread_id=thread_id)
        return True

    if atype == "VIDEO":
        video_id = attach.get("videoId")
        chat_id = msg.chat_id if msg else None
        message_id = msg.message_id if msg else None
        if video_id is not None and chat_id is not None and message_id:
            url = await client.download_video_url(
                video_id, chat_id=chat_id, message_id=message_id,
            )
            if url:
                data = await client.download_file(url)
                if data:
                    if await sender.send_video(
                        data,
                        caption=header_text,
                        filename=f"{video_id}.mp4",
                        message_thread_id=thread_id,
                    ):
                        return True
        elif video_id is not None:
            log.warning(
                "Cannot resolve VIDEO without chat/message context: videoId=%s",
                video_id,
            )

        thumb = attach.get("thumbnail")
        if thumb:
            data = await client.download_file(thumb)
            if data:
                if await sender.send_photo(
                    data,
                    caption=f"{header_text}\n<i>[видео — оригинал не удалось загрузить]</i>",
                    message_thread_id=thread_id,
                ):
                    return True
        await sender.send(
            f"{header_text}\n<i>[видео — не удалось загрузить]</i>",
            message_thread_id=thread_id,
        )
        return True

    if atype == "FILE":
        name = attach.get("name", "file")
        size = attach.get("size", 0)
        token_url = _extract_file_url(attach)
        file_id = attach.get("fileId")
        chat_id = msg.chat_id if msg else None
        message_id = msg.message_id if msg else None
        if (not token_url and file_id is not None
                and chat_id is not None and message_id):
            log.info(
                "Resolving FILE URL chatId=%s fileId=%s messageId=%s",
                chat_id, file_id, message_id,
            )
            resolved_url = await client.resolve_file_url(chat_id, message_id, file_id)
            if isinstance(resolved_url, str) and resolved_url.startswith("http"):
                token_url = resolved_url
                log.info("Resolved FILE URL for fileId=%s", file_id)
        if token_url:
            data = await client.download_file(token_url)
            if data:
                kind = _guess_media_kind(name)
                if kind == "photo":
                    sent = await sender.send_photo(data, caption=header_text, filename=name, message_thread_id=thread_id)
                elif kind == "video":
                    sent = await sender.send_video(data, caption=header_text, filename=name, message_thread_id=thread_id)
                else:
                    sent = await sender.send_document(data, caption=header_text, filename=name, message_thread_id=thread_id)
                if sent:
                    return True
        log.warning("FILE content unavailable; sending metadata only: fileId=%s name=%r", file_id, name)
        size_str = f" ({_human_size(size)})" if size else ""
        await sender.send(
            f"{header_text}\n📎 <b>{escape(name)}</b>{size_str}\n"
            "<i>[файл — не удалось загрузить]</i>",
            message_thread_id=thread_id,
        )
        return True

    if atype == "AUDIO":
        url = attach.get("url")
        if url:
            data = await client.download_file(url)
            if data:
                if await sender.send_voice(
                    data, caption=header_text, message_thread_id=thread_id
                ):
                    return True
        await sender.send(f"{header_text}\n{_attachment_failure(attach)}", message_thread_id=thread_id)
        return True

    if atype == "STICKER":
        url = attach.get("url")
        if url:
            data = await client.download_file(url)
            if data:
                if await sender.send_sticker(data, message_thread_id=thread_id):
                    return True
        await sender.send(f"{header_text}\n{_attachment_failure(attach)}", message_thread_id=thread_id)
        return True

    if atype == "SHARE":
        share_url = attach.get("url", "")
        title = attach.get("title", "")
        desc = attach.get("description", "")
        parts = [header_text]
        if title:
            parts.append(f"🔗 <b>{escape(title)}</b>")
        if share_url:
            parts.append(escape(share_url))
        if desc:
            parts.append(f"<i>{escape(desc[:200])}</i>")
        await sender.send("\n".join(parts), message_thread_id=thread_id)
        return True

    if atype == "LOCATION":
        lat = attach.get("lat") or attach.get("latitude")
        lon = attach.get("lon") or attach.get("lng") or attach.get("longitude")
        if lat and lon:
            await sender.send(f"{header_text}\n📍 {lat}, {lon}", message_thread_id=thread_id)
        else:
            await sender.send(f"{header_text}\n<i>[геолокация]</i>", message_thread_id=thread_id)
        return True

    if atype == "CONTACT":
        name = attach.get("name", "")
        phone = attach.get("phone", "")
        text = f"{header_text}\n👤 {escape(name)}"
        if phone:
            text += f" — {escape(phone)}"
        await sender.send(text, message_thread_id=thread_id)
        return True

    log.info("Unknown attach type %s, sending as info", atype)
    await sender.send(f"{header_text}\n<i>[вложение: {escape(atype or 'unknown')}]</i>", message_thread_id=thread_id)
    return True


async def _handle_linked_message(
    link: dict,
    link_type: str,
    header_text: str,
    client: PyMaxClient,
    sender: TelegramSender,
    resolver: ContactResolver,
    thread_id: int | None = None,
    msg: MaxMessage | None = None,
) -> None:
    """Handle FORWARD or REPLY link inside a message."""
    inner = link.get("message") or link
    fwd_sender_id = inner.get("sender") or link.get("sender")
    fwd_text = inner.get("text", "") or link.get("text", "")
    fwd_attaches = inner.get("attaches") or link.get("attaches") or []

    fwd_sender_label = ""
    if fwd_sender_id:
        fwd_sender_label = escape(await resolver.resolve_user(fwd_sender_id))

    if link_type == "FORWARD":
        prefix = "↩️ <b>Переслано</b>"
        if fwd_sender_label:
            prefix = f"↩️ <b>Переслано от {fwd_sender_label}</b>"
    else:
        prefix = "↩ <b>Ответ</b>"
        if fwd_sender_label:
            prefix = f"↩ <b>Ответ на {fwd_sender_label}</b>"

    full_header = f"{header_text}\n{prefix}"

    fwd_meaningful = [
        a for a in fwd_attaches
        if isinstance(a, dict) and a.get("_type") not in ("CONTROL", "WIDGET", "INLINE_KEYBOARD", None)
    ]

    if fwd_meaningful:
        group_caption = full_header
        if fwd_text:
            group_caption = f"{full_header}\n{escape(fwd_text)}"
        try:
            grouped = await _try_send_media_group(
                fwd_meaningful, client, sender, group_caption, thread_id, msg
            ) if msg else None
        except Exception:
            log.exception("Failed to prepare linked attachment group")
            grouped = None
        if grouped is True:
            return
        if grouped is False:
            await sender.send(
                f"{group_caption}\n<i>[группа вложений — не удалось загрузить]</i>",
                message_thread_id=thread_id,
            )
            return

        text_sent = False
        for i, attach in enumerate(fwd_meaningful):
            if i == 0 and fwd_text:
                cap = f"{full_header}\n{escape(fwd_text)}"
                text_sent = True
            else:
                cap = full_header
            try:
                await _send_attach(
                    attach, client, sender, cap, thread_id=thread_id, msg=msg
                )
            except Exception:
                log.exception(
                    "Failed to forward linked attach _type=%s",
                    attach.get("_type"),
                )
                await sender.send(
                    f"{cap}\n{_attachment_failure(attach)}",
                    message_thread_id=thread_id,
                )

        if fwd_text and not text_sent:
            await sender.send(f"{full_header}\n{escape(fwd_text)}", message_thread_id=thread_id)
    elif fwd_text:
        await sender.send(f"{full_header}\n{escape(fwd_text)}", message_thread_id=thread_id)
    else:
        await sender.send(f"{full_header}\n<i>[без содержимого]</i>", message_thread_id=thread_id)


def _human_size(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}" if unit == "Б" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def create_pymax_client(settings: Settings, sender: TelegramSender) -> PyMaxClient:
    client = PyMaxClient(settings)
    return configure_pymax_client(client, sender)


def configure_pymax_client(client: PyMaxClient, sender: TelegramSender):
    resolver = ContactResolver(client=client)
    # Expose for tg_handler commands like /profile.
    client.resolver = resolver

    _first_connect = True
    _notif_count = 0
    _last_notif_time: datetime | None = None

    def _can_notify() -> bool:
        if _last_notif_time is None:
            return True
        elapsed = (datetime.now() - _last_notif_time).total_seconds()
        if _notif_count == 1:
            return elapsed >= 3600    # 2-е: через 1 час
        if _notif_count == 2:
            return elapsed >= 10800   # 3-е: через 3 часа
        return elapsed >= 86400       # 4-е и далее: раз в сутки

    @client.on_ready
    async def handle_ready(snapshot: dict):
        nonlocal _first_connect
        participant_ids = resolver.load_snapshot(snapshot)

        if participant_ids:
            log.info("Batch-resolving %d participants...", len(participant_ids))
            await resolver.resolve_users_batch(participant_ids)
            log.info("Resolved users: %s", resolver.users)

            log.info("Known chats: %s", resolver.chats)
            log.info("Known users: %s", resolver.users)

        if not _first_connect:
            await sender.send("✅ <b>Max:</b> соединение восстановлено")
        else:
            chat_count = len(resolver.chats)
            await sender.send(f"✅ <b>Max:</b> подключён | чатов: {chat_count}")
        _first_connect = False

    @client.on_disconnect
    async def handle_disconnect():
        nonlocal _notif_count, _last_notif_time
        if not _can_notify():
            log.info("Disconnect notification suppressed (throttle)")
            return
        _notif_count += 1
        _last_notif_time = datetime.now()
        await sender.send("⚠️ <b>Max:</b> соединение потеряно, переподключение...")

    @client.on_message
    async def handle_message(msg: MaxMessage):
        log.info(
            "New message: chat=%s sender=%s is_self=%s text=%r attaches=%d",
            msg.chat_id,
            msg.sender_id,
            msg.is_self,
            (msg.text[:80] + "…") if len(msg.text) > 80 else msg.text,
            len(msg.attaches),
        )

        if msg.is_self:
            return

        raw_sender = await resolver.resolve_user(msg.sender_id)
        is_dm = resolver.is_dm(msg.chat_id)
        raw_chat = resolver.chat_name(msg.chat_id)

        # One forum topic per Max chat. Prefer a human title:
        # - DMs → the peer's name
        # - Groups with a known title → the chat title
        # - Chats discovered at runtime (no known title yet) → the sender's name
        #   (better than the numeric chat ID; ensure_topic will rename later if a
        #   real chat title appears).
        chat_title_known = raw_chat != str(msg.chat_id) and not raw_chat.startswith("DM:")
        if is_dm or not chat_title_known:
            topic_title = raw_sender
        else:
            topic_title = raw_chat

        existing_thread = sender.topic_store.get_topic(msg.chat_id)
        thread_id = await sender.ensure_topic(msg.chat_id, topic_title)

        # First time we touch this chat → publish a pinned profile card so the
        # topic starts with context (avatar, name, etc.).
        if existing_thread is None and thread_id is not None:
            from app.tg_handler import post_topic_intro
            asyncio.create_task(post_topic_intro(
                sender.bot, sender.chat_id, client, msg.chat_id, thread_id,
            ))

        sender_label = escape(raw_sender)
        chat_label = escape(raw_chat)
        header_text = _header(msg, sender_label, chat_label, is_dm)

        link = msg.link
        link_type = link.get("type") if isinstance(link, dict) else None

        if link_type in ("FORWARD", "REPLY"):
            await _handle_linked_message(link, link_type, header_text, client, sender, resolver, thread_id=thread_id, msg=msg)
            if msg.text:
                await sender.send(f"{header_text}\n{escape(msg.text)}", message_thread_id=thread_id)
            log.info("Forwarded link type=%s → TG", link_type)
            return

        meaningful_attaches = [
            a for a in msg.attaches
            if isinstance(a, dict) and a.get("_type") not in ("CONTROL", "WIDGET", "INLINE_KEYBOARD", None)
        ]

        if meaningful_attaches:
            group_caption = header_text
            if msg.text:
                group_caption = f"{header_text}\n{escape(msg.text)}"
            try:
                grouped = await _try_send_media_group(
                    meaningful_attaches,
                    client,
                    sender,
                    group_caption,
                    thread_id,
                    msg,
                )
            except Exception:
                log.exception("Failed to prepare attachment group")
                grouped = None
            if grouped is True:
                log.info("Forwarded %d attachments as media group", len(meaningful_attaches))
                return
            if grouped is False:
                await sender.send(
                    f"{group_caption}\n<i>[группа вложений — не удалось загрузить]</i>",
                    message_thread_id=thread_id,
                )
                return

            text_sent = False
            for i, attach in enumerate(meaningful_attaches):
                if i == 0 and msg.text:
                    cap = f"{header_text}\n{escape(msg.text)}"
                    text_sent = True
                else:
                    cap = header_text
                try:
                    await _send_attach(
                        attach, client, sender, cap, thread_id=thread_id, msg=msg
                    )
                except Exception:
                    log.exception(
                        "Failed to forward attach _type=%s",
                        attach.get("_type"),
                    )
                    await sender.send(
                        f"{cap}\n{_attachment_failure(attach)}",
                        message_thread_id=thread_id,
                    )
                log.info("Processed attach _type=%s", attach.get("_type"))

            if msg.text and not text_sent:
                await sender.send(f"{header_text}\n{escape(msg.text)}", message_thread_id=thread_id)
        else:
            body = escape(msg.text) if msg.text else "<i>[нетекстовое сообщение]</i>"
            await sender.send(f"{header_text}\n{body}", message_thread_id=thread_id)
            log.info("Forwarded text → TG")

    return client
