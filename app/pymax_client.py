from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import aiohttp
from yarl import URL

from app.config import Settings
from app.pymax_auth import build_pymax_client

log = logging.getLogger(__name__)

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0.0.0 Safari/537.36"
_BROWSER_HEADERS = {"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"}
_HTTP_HEADERS = {**_BROWSER_HEADERS, "Origin": "https://web.max.ru", "Referer": "https://web.max.ru/", "Accept": "*/*"}
_ALLOWED_DOWNLOAD_HOSTS = frozenset({"i.oneme.ru", "oneme.ru", "web.max.ru", "max.ru"})
_ALLOWED_DOWNLOAD_SUFFIXES = (".oneme.ru", ".max.ru", ".okcdn.ru")


def _is_allowed_download_url(url: str) -> bool:
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return False
    host = (parsed.hostname or "").lower().rstrip(".")
    return parsed.scheme == "https" and (
        host in _ALLOWED_DOWNLOAD_HOSTS
        or any(host.endswith(suffix) for suffix in _ALLOWED_DOWNLOAD_SUFFIXES)
    )


def _redact_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
        query = [(key, "<redacted>") for key, _ in parse_qsl(parsed.query, keep_blank_values=True)]
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    except (TypeError, ValueError):
        return "<invalid-url>"


@dataclass
class MaxMessage:
    chat_id: Any = None
    sender_id: Any = None
    text: str = ""
    timestamp: Any = None
    message_id: str = ""
    is_self: bool = False
    attaches: list = field(default_factory=list)
    link: dict = field(default_factory=dict)
    raw: dict = field(default_factory=dict)


def _plain(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {_plain(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_plain(v) for v in value]
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    return value


def _model_dict(value: Any) -> dict:
    if value is None:
        return {}
    if isinstance(value, dict):
        return _plain(value)
    if hasattr(value, "model_dump"):
        try:
            return _plain(value.model_dump(by_alias=True, mode="json"))
        except UnicodeDecodeError:
            return _plain(value.model_dump(by_alias=True, mode="python"))
    return _plain(vars(value))


def _attachment_to_dict(attach: Any) -> dict:
    data = _model_dict(attach)
    atype = data.get("_type") or data.get("type")
    if isinstance(atype, str):
        data["_type"] = atype
    if "base_url" in data and "baseUrl" not in data:
        data["baseUrl"] = data["base_url"]
    if "file_id" in data and "fileId" not in data:
        data["fileId"] = data["file_id"]
    if "video_id" in data and "videoId" not in data:
        data["videoId"] = data["video_id"]
    if "audio_id" in data and "audioId" not in data:
        data["audioId"] = data["audio_id"]
    if "photo_url" in data and "photoUrl" not in data:
        data["photoUrl"] = data["photo_url"]
    return data


def _message_from_pymax(message: Any, my_id: Any = None) -> MaxMessage | None:
    chat_id = getattr(message, "chat_id", None)
    if chat_id is None:
        return None

    sender_id = getattr(message, "sender", None)
    raw = _model_dict(message)
    return MaxMessage(
        chat_id=chat_id,
        sender_id=sender_id,
        text=getattr(message, "text", "") or "",
        timestamp=getattr(message, "time", None),
        message_id=str(getattr(message, "id", "")),
        is_self=bool(my_id is not None and sender_id == my_id),
        attaches=[
            _attachment_to_dict(attach)
            for attach in (getattr(message, "attaches", None) or [])
        ],
        link=_model_dict(getattr(message, "link", None)),
        raw=raw,
    )


def _name_to_dict(name: Any) -> dict:
    data = _model_dict(name)
    if "first_name" in data and "firstName" not in data:
        data["firstName"] = data["first_name"]
    if "last_name" in data and "lastName" not in data:
        data["lastName"] = data["last_name"]
    return data


def _user_to_dict(user: Any) -> dict:
    data = _model_dict(user)
    names = getattr(user, "names", None)
    if names is not None:
        data["names"] = [_name_to_dict(name) for name in names]
    if "base_url" in data and "baseUrl" not in data:
        data["baseUrl"] = data["base_url"]
    if "base_raw_url" in data and "baseRawUrl" not in data:
        data["baseRawUrl"] = data["base_raw_url"]
    return data


def _chat_to_dict(chat: Any) -> dict:
    data = _model_dict(chat)
    if "base_icon_url" in data and "baseIconUrl" not in data:
        data["baseIconUrl"] = data["base_icon_url"]
    if "base_raw_icon_url" in data and "baseRawIconUrl" not in data:
        data["baseRawIconUrl"] = data["base_raw_icon_url"]
    return data


class PyMaxClient:
    """Bridge client backed exclusively by PyMax."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.max_download_bytes = settings.max_download_mb * 1024 * 1024
        self.chat_ids: list[int] = []
        if settings.max_chat_ids:
            self.chat_ids += map(int, map(str.strip, settings.max_chat_ids.split(",")))

        self._client = build_pymax_client(settings)
        self._my_id: Any = None
        self._on_ready_cb = None
        self._on_message_cb = None
        self._on_disconnect_cb = None
        self.resolver = None

        self._wire_events()

    @property
    def raw_client(self):
        return self._client

    def on_ready(self, func):
        self._on_ready_cb = func
        return func

    def on_message(self, func):
        self._on_message_cb = func
        return func

    def on_disconnect(self, func):
        self._on_disconnect_cb = func
        return func

    def _wire_events(self) -> None:
        @self._client.on_start()
        async def _handle_start(pymax_client):
            self._my_id = self._extract_my_id(pymax_client)
            snapshot = self._build_snapshot(pymax_client)
            await self._add_configured_chats(snapshot)
            if self._on_ready_cb:
                await self._on_ready_cb(snapshot)

        @self._client.on_message()
        async def _handle_message(message, pymax_client):
            bridge_message = _message_from_pymax(message, self._my_id)
            if bridge_message is None:
                return
            if self.chat_ids and bridge_message.chat_id not in self.chat_ids:
                return
            if self._on_message_cb:
                await self._on_message_cb(bridge_message)

        @self._client.on_disconnect()
        async def _handle_disconnect(exc, reconnect, delay):
            log.warning(
                "PyMax disconnected: %s; reconnect=%s delay=%s",
                exc,
                reconnect,
                delay,
            )
            if self._on_disconnect_cb:
                await self._on_disconnect_cb()

    async def run(self):
        await self._client.start()

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close:
            await close()

    async def stop(self) -> None:
        stop = getattr(self._client, "stop", None)
        if stop:
            await stop()
            return
        await self.close()

    async def fetch_contacts(self, contact_ids: list[int]) -> dict:
        if not contact_ids:
            return {}
        users = await self._client.get_users(contact_ids)
        return {"contacts": [_user_to_dict(user) for user in users if user]}

    async def resolve_file_url(self, chat_id, message_id, file_id) -> str | None:
        result = await self._client.get_file_by_id(int(chat_id), int(message_id), int(file_id))
        url = _model_dict(result).get("url")
        return url if isinstance(url, str) else None

    async def send_message(
        self,
        chat_id,
        text: str = "",
        elements=None,
        attaches=None,
    ) -> dict:
        try:
            message = await self._client.send_message(
                int(chat_id),
                text=text or None,
                attachments=attaches or None,
                notify=True,
            )
        except Exception as exc:
            log.exception("PyMax send_message failed for chat %s", chat_id)
            return {"_max_error": {"message": str(exc)}}
        return _model_dict(message) or {"ok": True}

    async def upload_photo(
        self,
        data: bytes,
        chat_id=None,
        filename: str = "image.jpg",
        mimetype: str = "image/jpeg",
    ):
        from pymax import Photo

        return Photo(raw=data, name=filename)

    async def upload_file(
        self,
        data: bytes,
        chat_id=None,
        filename: str = "file.bin",
        mimetype: str = "application/octet-stream",
        attach_type: str = "FILE",
        timeout: float = 60.0,
    ):
        from pymax import File

        return File(raw=data, name=filename)

    async def upload_video(
        self,
        data: bytes,
        chat_id=None,
        filename: str = "video.mp4",
        mimetype: str = "video/mp4",
        timeout: float = 60.0,
    ):
        from pymax import Video

        return Video(raw=data, name=filename)

    async def upload_audio(
        self,
        data: bytes,
        chat_id=None,
        filename: str = "voice.ogg",
        mimetype: str = "audio/ogg",
        duration: int | None = None,
        timeout: float = 60.0,
    ):
        from pymax import Voice

        return Voice(raw=data, name=filename, duration=duration)

    async def open_by_link(self, link: str) -> dict:
        try:
            chat = await self._client.join_group(link)
        except ValueError:
            try:
                chat = await self._client.join_channel(link)
            except Exception as exc:
                log.exception("PyMax open_by_link failed: %s", _redact_url(link))
                return {"_max_error": {"message": str(exc)}}
        except Exception as exc:
            log.exception("PyMax open_by_link failed: %s", _redact_url(link))
            return {"_max_error": {"message": str(exc)}}
        return {"chatId": getattr(chat, "id", None), "chat": _chat_to_dict(chat)}

    async def download_audio_url(
        self,
        audio_id,
        chat_id,
        message_id,
        token: str | None = None,
    ) -> str | None:
        if token:
            return f"https://i.oneme.ru/i?r={token}"
        return None

    async def download_video_url(self, video_id, chat_id, message_id) -> str | None:
        video = await self._client.get_video_by_id(
            int(chat_id),
            int(message_id),
            int(video_id),
        )
        data = _model_dict(video)
        url = data.get("url")
        return url if isinstance(url, str) else None

    async def download_file(self, url: str) -> bytes | None:
        if not _is_allowed_download_url(url):
            log.warning("Blocked download from disallowed URL: %s", _redact_url(url)[:120])
            return None

        host = (urlsplit(url).hostname or "").lower().rstrip(".")
        is_okcdn = host == "okcdn.ru" or host.endswith(".okcdn.ru")
        if is_okcdn:
            session = aiohttp.ClientSession(headers={"User-Agent": _USER_AGENT})
            request_headers = {}
            request_url = URL(url, encoded=True)
        else:
            session = aiohttp.ClientSession(headers=_BROWSER_HEADERS)
            request_headers = _HTTP_HEADERS
            request_url = url
        try:
            async with session.get(
                request_url,
                headers=request_headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status != 200:
                    error_body = (await resp.text(errors="replace"))[:200]
                    log.warning(
                        "Download failed %s - HTTP %d: %r",
                        _redact_url(url)[:120],
                        resp.status,
                        error_body,
                    )
                    return None

                declared = resp.headers.get("Content-Length")
                try:
                    declared_size = int(declared) if declared else None
                except ValueError:
                    declared_size = None
                if declared_size is not None and declared_size > self.max_download_bytes:
                    log.warning(
                        "Blocked oversized download %s: %s bytes > %s bytes",
                        _redact_url(url)[:120],
                        declared_size,
                        self.max_download_bytes,
                    )
                    return None

                chunks: list[bytes] = []
                total = 0
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > self.max_download_bytes:
                        log.warning(
                            "Blocked oversized streaming download %s: %d bytes > %d bytes",
                            _redact_url(url)[:120],
                            total,
                            self.max_download_bytes,
                        )
                        return None
                    chunks.append(chunk)
                return b"".join(chunks)
        except Exception:
            log.exception("Download error: %s", _redact_url(url)[:120])
            return None
        finally:
            await session.close()

    def _extract_my_id(self, pymax_client) -> Any:
        me = getattr(pymax_client, "me", None)
        contact = getattr(me, "contact", None)
        return getattr(contact, "id", None)

    def _build_snapshot(self, pymax_client) -> dict:
        me = getattr(pymax_client, "me", None)
        contact = getattr(me, "contact", None)
        chats = getattr(pymax_client, "chats", None) or []
        contacts = getattr(pymax_client, "contacts", None) or []
        return {
            "profile": _user_to_dict(contact) if contact is not None else {},
            "chats": [_chat_to_dict(chat) for chat in chats if chat],
            "contacts": [_user_to_dict(user) for user in contacts if user],
        }

    async def _add_configured_chats(self, snapshot: dict) -> None:
        """Fetch filtered chats omitted from PyMax's incremental login sync."""
        if not self.chat_ids:
            return

        known_ids = {chat.get("id") for chat in snapshot["chats"]}
        missing_ids = [chat_id for chat_id in self.chat_ids if chat_id not in known_ids]
        if not missing_ids:
            return

        try:
            chats = await self._client.get_chats(missing_ids)
        except Exception:
            log.exception("PyMax failed to fetch configured chats: %s", missing_ids)
            return

        snapshot["chats"].extend(_chat_to_dict(chat) for chat in chats if chat)
