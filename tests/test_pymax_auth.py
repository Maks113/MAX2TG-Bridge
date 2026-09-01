import sys
import types

import pytest

from app.config import Settings
from app.pymax_auth import EnvPasswordProvider, LoggingQrHandler, build_pymax_client


class FakeExtraConfig:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class FakeWebClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _install_fake_pymax(monkeypatch):
    fake = types.SimpleNamespace(
        Client=FakeClient,
        ExtraConfig=FakeExtraConfig,
        WebClient=FakeWebClient,
    )
    monkeypatch.setitem(sys.modules, "pymax", fake)


def test_builds_sms_client(monkeypatch):
    _install_fake_pymax(monkeypatch)
    settings = Settings(
        tg_bot_token="tg",
        tg_chat_id="-100",
        max_pymax_auth="sms",
        max_phone="+79990000000",
        max_pymax_work_dir="cache/max",
        max_pymax_session_name="main.db",
        max_2fa_password="secret",
        tg_proxy="socks5://127.0.0.1:1080",
        debug=True,
    )

    client = build_pymax_client(settings)

    assert isinstance(client, FakeClient)
    assert client.kwargs["phone"] == "+79990000000"
    assert client.kwargs["work_dir"] == "cache/max"
    assert client.kwargs["session_name"] == "main.db"
    assert isinstance(client.kwargs["password_provider"], EnvPasswordProvider)
    extra_config = client.kwargs["extra_config"]
    assert extra_config.kwargs["proxy"] == "socks5://127.0.0.1:1080"
    assert extra_config.kwargs["log_level"] == "DEBUG"


def test_builds_qr_web_client(monkeypatch):
    _install_fake_pymax(monkeypatch)
    settings = Settings(
        tg_bot_token="tg",
        tg_chat_id="-100",
        max_pymax_auth="qr",
        max_pymax_work_dir="cache/max",
        max_pymax_session_name="web.db",
    )

    client = build_pymax_client(settings)

    assert isinstance(client, FakeWebClient)
    assert client.kwargs["work_dir"] == "cache/max"
    assert client.kwargs["session_name"] == "web.db"
    assert isinstance(client.kwargs["qr_provider"], LoggingQrHandler)
    assert client.kwargs["extra_config"].kwargs["log_level"] == "INFO"


def test_sms_client_requires_phone(monkeypatch):
    _install_fake_pymax(monkeypatch)
    settings = Settings(
        tg_bot_token="tg",
        tg_chat_id="-100",
        max_pymax_auth="sms",
        max_phone=None,
    )

    with pytest.raises(RuntimeError) as exc:
        build_pymax_client(settings)

    assert "MAX_PHONE" in str(exc.value)
