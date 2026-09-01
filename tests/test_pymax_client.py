import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app.max_client import OpCode
from app.pymax_client import PyMaxClientAdapter, _pymax_message_to_legacy


class FakeModel:
    def __init__(self, **data):
        self.__dict__.update(data)

    def model_dump(self, by_alias=False, mode="python"):
        return dict(self.__dict__)


class FakeRawClient:
    def __init__(self):
        self.start_handlers = []
        self.message_handlers = []
        self.disconnect_handlers = []
        self.me = SimpleNamespace(
            contact=FakeModel(
                id=7,
                names=[FakeModel(firstName="Max", lastName="User")],
            )
        )
        self.chats = [
            FakeModel(id=10, type="DIALOG", title=None, participants={7: 0, 8: 0}),
            FakeModel(id=20, type="CHAT", title="Team", participants={7: 0, 9: 0}),
        ]
        self.contacts = [FakeModel(id=8, names=[FakeModel(firstName="Peer")])]
        self.get_users = AsyncMock(
            return_value=[FakeModel(id=8, names=[FakeModel(firstName="Peer")])]
        )
        self.get_chats = AsyncMock(return_value=self.chats)
        self.get_file_by_id = AsyncMock(
            return_value=FakeModel(url="https://i.oneme.ru/file.bin", unsafe=False)
        )
        self.get_video_by_id = AsyncMock(
            return_value=FakeModel(url="https://i.oneme.ru/video.mp4")
        )
        self.send_message = AsyncMock(return_value=FakeModel(id=123, chatId=20))

    def on_start(self):
        def decorator(func):
            self.start_handlers.append(func)
            return func
        return decorator

    def on_message(self):
        def decorator(func):
            self.message_handlers.append(func)
            return func
        return decorator

    def on_disconnect(self):
        def decorator(func):
            self.disconnect_handlers.append(func)
            return func
        return decorator

    async def start(self):
        for handler in self.start_handlers:
            await handler(self)


@pytest.fixture
def adapter(monkeypatch):
    raw = FakeRawClient()
    monkeypatch.setattr("app.pymax_client.build_pymax_client", lambda settings: raw)
    settings = Settings(
        tg_bot_token="tg",
        tg_chat_id="-100",
        max_client_backend="pymax",
        max_pymax_auth="sms",
        max_phone="+79990000000",
    )
    return PyMaxClientAdapter(settings), raw


def test_converts_pymax_message_to_legacy_shape():
    message = FakeModel(
        id=55,
        chat_id=20,
        sender=8,
        text="hello",
        time=123456,
        attaches=[FakeModel(_type="PHOTO", baseUrl="https://i.oneme.ru/i?r=x")],
        link=None,
    )

    legacy = _pymax_message_to_legacy(message, my_id=7)

    assert legacy.chat_id == 20
    assert legacy.sender_id == 8
    assert legacy.message_id == "55"
    assert legacy.text == "hello"
    assert legacy.is_self is False
    assert legacy.attaches == [{"_type": "PHOTO", "baseUrl": "https://i.oneme.ru/i?r=x"}]


async def test_run_emits_ready_snapshot(adapter):
    client, _ = adapter
    on_ready = AsyncMock()
    client.on_ready(on_ready)

    await client.run()

    snapshot = on_ready.await_args.args[0]
    assert snapshot["profile"]["id"] == 7
    assert snapshot["chats"][1]["title"] == "Team"
    assert snapshot["contacts"][0]["id"] == 8


async def test_message_handler_receives_legacy_message(adapter):
    client, raw = adapter
    on_message = AsyncMock()
    client.on_message(on_message)
    pymax_message = FakeModel(
        id=77,
        chat_id=20,
        sender=8,
        text="from pymax",
        time=100,
        attaches=[],
        link=None,
    )

    await raw.message_handlers[0](pymax_message, raw)

    msg = on_message.await_args.args[0]
    assert msg.chat_id == 20
    assert msg.text == "from pymax"


async def test_send_message_delegates_to_pymax(adapter):
    client, raw = adapter

    resp = await client.send_message(20, "hello", elements=[{"type": "STRONG"}])

    raw.send_message.assert_awaited_once_with(
        20,
        text="hello",
        attachments=None,
        notify=True,
    )
    assert resp["id"] == 123


async def test_cmd_supports_contacts_and_file_download(adapter):
    client, raw = adapter

    contacts = await client.cmd(OpCode.CONTACT_GET, {"contactIds": [8]})
    file_info = await client.cmd(
        OpCode.FILE_DOWNLOAD_URL,
        {"chatId": 20, "messageId": "77", "fileId": 99},
    )

    raw.get_users.assert_awaited_once_with([8])
    raw.get_file_by_id.assert_awaited_once_with(20, "77", 99)
    assert contacts["contacts"][0]["id"] == 8
    assert file_info["url"] == "https://i.oneme.ru/file.bin"


async def test_upload_wrappers_return_pymax_files(monkeypatch, adapter):
    class FakePhoto:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class FakeFile:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_pymax = types.SimpleNamespace(Photo=FakePhoto, File=FakeFile)
    monkeypatch.setitem(sys.modules, "pymax", fake_pymax)
    client, _ = adapter

    photo = await client.upload_photo(b"img", filename="image.jpg")
    file = await client.upload_file(b"doc", filename="doc.txt")

    assert isinstance(photo, FakePhoto)
    assert photo.kwargs == {"raw": b"img", "name": "image.jpg"}
    assert isinstance(file, FakeFile)
    assert file.kwargs == {"raw": b"doc", "name": "doc.txt"}
