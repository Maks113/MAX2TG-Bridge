import os
from unittest.mock import patch

import pytest

from app.config import Settings, load_settings


def load(env):
    with patch("app.config.load_dotenv"), patch.dict(os.environ, env, clear=True):
        return load_settings()


BASE = {"TG_BOT_TOKEN": "token", "TG_CHAT_ID": "-100"}


def test_qr_is_default_and_needs_no_extra_credentials():
    settings = load(BASE)
    assert settings.max_pymax_auth == "qr"
    assert settings.max_pymax_session_name == "pymax-qr.db"


def test_sms_requires_phone():
    with pytest.raises(SystemExit, match="MAX_PHONE"):
        load({**BASE, "MAX_PYMAX_AUTH": "sms"})


def test_sms_configuration():
    settings = load({**BASE, "MAX_PYMAX_AUTH": "sms", "MAX_PHONE": "+79990000000"})
    assert settings.max_phone == "+79990000000"
    assert settings.max_pymax_session_name == "pymax-sms.db"


def test_rejects_unknown_auth_mode():
    with pytest.raises(SystemExit, match="MAX_PYMAX_AUTH"):
        load({**BASE, "MAX_PYMAX_AUTH": "invalid"})


def test_chat_and_user_filters():
    settings = load({**BASE, "MAX_CHAT_IDS": "-1,-2", "TG_ALLOWED_USER_IDS": "10,20"})
    assert settings.max_chat_ids == "-1,-2"
    assert settings.tg_allowed_user_ids == frozenset({10, 20})


def test_media_limits():
    settings = load({**BASE, "MAX_DOWNLOAD_MB": "25", "TG_UPLOAD_MB": "30"})
    assert settings.max_download_mb == 25
    assert settings.tg_upload_mb == 30


def test_invalid_chat_id():
    with pytest.raises(SystemExit, match="TG_CHAT_ID"):
        load({**BASE, "TG_CHAT_ID": "invalid"})


def test_settings_are_frozen():
    settings = Settings(tg_bot_token="token", tg_chat_id="-100")
    with pytest.raises((AttributeError, TypeError)):
        settings.debug = True
