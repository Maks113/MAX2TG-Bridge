"""Tests for app/tg_handler.py — topic-based reply routing."""

from unittest.mock import AsyncMock, MagicMock

from telegram.error import TimedOut

from app.tg_handler import (
    ALLOWED_USER_KEY,
    MAX_UPLOAD_BYTES_KEY,
    MAX_CLIENT_KEY,
    TOPIC_STORE_KEY,
    _download_tg_file,
    _on_topic_message,
    _send_topic_media_messages,
    build_tg_app,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_topic_store(mapping: dict | None = None):
    """A TopicStore stand-in: chat_for_topic(thread_id) → max_chat_id."""
    mapping = mapping or {10: 42}
    store = MagicMock()
    store.chat_for_topic = MagicMock(side_effect=lambda tid: mapping.get(tid))
    return store


def _make_update(text="Hello", thread_id=10, is_topic_message=True, user_id=100):
    update = MagicMock()
    update.message = MagicMock()
    update.message.text = text
    update.message.message_thread_id = thread_id
    update.message.is_topic_message = is_topic_message
    update.message.reply_text = AsyncMock()
    update.message.set_reaction = AsyncMock()
    update.effective_user = MagicMock()
    update.effective_user.id = user_id
    return update


def _make_context(max_client=None, topic_store=None, allowed_user_id=None):
    ctx = MagicMock()
    bot_data = {ALLOWED_USER_KEY: allowed_user_id}
    if max_client is not None:
        bot_data[MAX_CLIENT_KEY] = max_client
    if topic_store is not None:
        bot_data[TOPIC_STORE_KEY] = topic_store
    ctx.bot_data = bot_data
    return ctx


# ---------------------------------------------------------------------------
# _on_topic_message
# ---------------------------------------------------------------------------

class TestOnTopicMessage:
    async def test_routes_topic_text_to_max(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock(return_value={"ok": True})

        update = _make_update("Hello", thread_id=10)
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store({10: 42}))

        await _on_topic_message(update, ctx)

        max_client.send_message.assert_called_once_with(42, "Hello", elements=[])

    async def test_reacts_on_success(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock(return_value={"ok": True})

        update = _make_update()
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store())

        await _on_topic_message(update, ctx)

        update.message.set_reaction.assert_called_once()

    async def test_ignores_general_topic(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock()

        update = _make_update(thread_id=None, is_topic_message=False)
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store())

        await _on_topic_message(update, ctx)

        max_client.send_message.assert_not_called()

    async def test_ignores_unknown_topic(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock()

        update = _make_update(thread_id=999)
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store({10: 42}))

        await _on_topic_message(update, ctx)

        max_client.send_message.assert_not_called()

    async def test_ignores_empty_text(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock()

        update = _make_update(text=None)
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store())

        await _on_topic_message(update, ctx)

        max_client.send_message.assert_not_called()

    async def test_respects_allowed_user_id(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock()

        update = _make_update(user_id=555)
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store(),
                            allowed_user_id=100)

        await _on_topic_message(update, ctx)

        max_client.send_message.assert_not_called()

    async def test_allows_matching_user_id(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock(return_value={"ok": True})

        update = _make_update(user_id=100)
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store(),
                            allowed_user_id=100)

        await _on_topic_message(update, ctx)

        max_client.send_message.assert_called_once()

    async def test_warns_when_max_client_missing(self):
        update = _make_update()
        ctx = _make_context(topic_store=_make_topic_store())

        await _on_topic_message(update, ctx)

        update.message.reply_text.assert_called_once()
        assert "⚠️" in update.message.reply_text.call_args[0][0]

    async def test_warns_on_send_failure(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock(return_value=None)

        update = _make_update()
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store())

        await _on_topic_message(update, ctx)

        update.message.reply_text.assert_called_once()
        assert "⚠️" in update.message.reply_text.call_args[0][0]

    async def test_warns_on_exception(self):
        max_client = MagicMock()
        max_client.send_message = AsyncMock(side_effect=RuntimeError("boom"))

        update = _make_update()
        ctx = _make_context(max_client=max_client, topic_store=_make_topic_store())

        await _on_topic_message(update, ctx)

        update.message.reply_text.assert_called_once()
        assert "⚠️" in update.message.reply_text.call_args[0][0]


# ---------------------------------------------------------------------------
# build_tg_app
# ---------------------------------------------------------------------------

class TestBuildTgApp:
    def test_wires_bot_data(self):
        max_client = MagicMock()
        topic_store = _make_topic_store()

        app = build_tg_app("123456:AAABBBCCC", max_client, "-100123456",
                            topic_store, allowed_user_id=777)

        assert app.bot_data[MAX_CLIENT_KEY] is max_client
        assert app.bot_data[TOPIC_STORE_KEY] is topic_store
        assert app.bot_data[ALLOWED_USER_KEY] == frozenset({777})
        assert app.bot_data[MAX_UPLOAD_BYTES_KEY] == 50 * 1024 * 1024

    def test_wires_custom_max_upload_bytes(self):
        app = build_tg_app(
            "123456:AAABBBCCC",
            MagicMock(),
            "-100123456",
            _make_topic_store(),
            max_upload_bytes=123,
        )

        assert app.bot_data[MAX_UPLOAD_BYTES_KEY] == 123

    def test_allowed_user_id_none_when_unset(self):
        app = build_tg_app("123456:AAABBBCCC", MagicMock(), "-100123456",
                            _make_topic_store())

        assert app.bot_data[ALLOWED_USER_KEY] is None

    def test_registers_message_handler(self):
        app = build_tg_app("123456:AAABBBCCC", MagicMock(), "-100123456",
                            _make_topic_store())

        assert app.handlers[0]


class TestMediaGrouping:
    async def test_sends_album_as_one_max_message(self, monkeypatch):
        first = MagicMock()
        first.caption = "Album caption"
        first.caption_entities = []
        first.reply_text = AsyncMock()
        first.set_reaction = AsyncMock()
        second = MagicMock()
        second.caption = None
        second.caption_entities = []
        second.reply_text = AsyncMock()
        second.set_reaction = AsyncMock()
        uploader = AsyncMock(side_effect=["attach-1", "attach-2"])
        monkeypatch.setattr("app.tg_handler._upload_topic_attachment", uploader)
        max_client = MagicMock()
        max_client.send_message = AsyncMock(return_value={"ok": True})

        await _send_topic_media_messages(
            [first, second], 42, max_client, 1024
        )

        max_client.send_message.assert_awaited_once_with(
            42,
            text="Album caption",
            elements=[],
            attaches=["attach-1", "attach-2"],
        )
        first.set_reaction.assert_awaited_once()


# ---------------------------------------------------------------------------
# _download_tg_file
# ---------------------------------------------------------------------------

class TestDownloadTgFile:
    async def test_refuses_declared_oversized_file(self):
        file_obj = MagicMock()
        file_obj.file_size = 101
        file_obj.get_file = AsyncMock()

        data = await _download_tg_file(file_obj, max_bytes=100)

        assert data is None
        file_obj.get_file.assert_not_called()

    async def test_refuses_downloaded_oversized_file(self):
        tg_file = MagicMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"abcdef"))
        file_obj = MagicMock()
        file_obj.file_size = None
        file_obj.get_file = AsyncMock(return_value=tg_file)

        data = await _download_tg_file(file_obj, max_bytes=5)

        assert data is None

    async def test_retries_telegram_timeout(self, monkeypatch):
        tg_file = MagicMock()
        tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"ok"))
        file_obj = MagicMock()
        file_obj.file_size = 2
        file_obj.get_file = AsyncMock(side_effect=[TimedOut(), tg_file])
        monkeypatch.setattr("app.tg_handler.asyncio.sleep", AsyncMock())

        data = await _download_tg_file(file_obj, max_bytes=10)

        assert data == b"ok"
        assert file_obj.get_file.await_count == 2
