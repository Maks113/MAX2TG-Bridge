import os
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv

MaxClientBackend = Literal["legacy", "pymax"]
PyMaxAuthMode = Literal["sms", "qr"]


@dataclass(frozen=True)
class Settings:
    tg_bot_token: str
    tg_chat_id: str
    max_token: str | None = None
    max_device_id: str | None = None
    max_client_backend: MaxClientBackend = "legacy"
    max_pymax_auth: PyMaxAuthMode = "sms"
    max_phone: str | None = None
    max_pymax_work_dir: str = "state/pymax"
    max_pymax_session_name: str = "pymax-sms.db"
    max_2fa_password: str | None = None
    max_chat_ids: str | None = None
    tg_proxy: str | None = None
    debug: bool = False
    reply_enabled: bool = False
    state_dir: str = "state"
    tg_allowed_user_ids: frozenset[int] | None = None
    debug_dump_json: bool = False
    max_download_mb: int = 50
    tg_upload_mb: int = 50


def _normalized_choice(name: str, default: str, allowed: set[str]) -> str:
    raw = os.environ.get(name)
    value = (raw or default).strip().lower()
    if value not in allowed:
        expected = ", ".join(sorted(allowed))
        raise SystemExit(f"{name} must be one of: {expected}; got: {raw!r}")
    return value


def load_settings() -> Settings:
    load_dotenv()

    max_client_backend = _normalized_choice(
        "MAX_CLIENT_BACKEND", "legacy", {"legacy", "pymax"}
    )
    max_pymax_auth = _normalized_choice("MAX_PYMAX_AUTH", "sms", {"sms", "qr"})

    required = ["TG_BOT_TOKEN", "TG_CHAT_ID"]
    if max_client_backend == "legacy":
        required += ["MAX_TOKEN", "MAX_DEVICE_ID"]
    elif max_pymax_auth == "sms":
        required += ["MAX_PHONE"]

    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise SystemExit(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in the values."
        )

    tg_chat_id = os.environ["TG_CHAT_ID"]
    try:
        int(tg_chat_id)
    except ValueError:
        raise SystemExit(
            f"TG_CHAT_ID must be a valid integer, got: {tg_chat_id!r}"
        )

    allowed_raw = (os.environ.get("TG_ALLOWED_USER_IDS")
                   or os.environ.get("TG_ALLOWED_USER_ID") or None)
    allowed_user_ids: frozenset[int] | None = None
    if allowed_raw:
        try:
            allowed_user_ids = frozenset(
                int(value.strip()) for value in allowed_raw.split(",") if value.strip()
            )
        except ValueError:
            raise SystemExit(
                "TG_ALLOWED_USER_IDS must be a comma-separated list of integers, "
                f"got: {allowed_raw!r}"
            )
        if not allowed_user_ids:
            allowed_user_ids = None

    def _int_env(name: str, default: int) -> int:
        raw = os.environ.get(name)
        if not raw:
            return default
        try:
            value = int(raw)
        except ValueError:
            raise SystemExit(f"{name} must be a valid integer, got: {raw!r}")
        if value <= 0:
            raise SystemExit(f"{name} must be greater than zero, got: {value!r}")
        return value

    state_dir = os.environ.get("STATE_DIR") or "state"
    max_pymax_work_dir = (
        os.environ.get("MAX_PYMAX_WORK_DIR")
        or os.path.join(state_dir, "pymax")
    )
    max_pymax_session_name = (
        os.environ.get("MAX_PYMAX_SESSION_NAME")
        or f"pymax-{max_pymax_auth}.db"
    )

    return Settings(
        tg_bot_token=os.environ["TG_BOT_TOKEN"],
        tg_chat_id=tg_chat_id,
        max_token=os.environ.get("MAX_TOKEN") or None,
        max_device_id=os.environ.get("MAX_DEVICE_ID") or None,
        max_client_backend=max_client_backend,  # type: ignore[arg-type]
        max_pymax_auth=max_pymax_auth,  # type: ignore[arg-type]
        max_phone=os.environ.get("MAX_PHONE") or None,
        max_pymax_work_dir=max_pymax_work_dir,
        max_pymax_session_name=max_pymax_session_name,
        max_2fa_password=os.environ.get("MAX_2FA_PASSWORD") or None,
        max_chat_ids=os.environ.get("MAX_CHAT_IDS") or None,
        tg_proxy=os.environ.get("TG_PROXY") or None,
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
        reply_enabled=os.environ.get("REPLY_ENABLED", "").lower() in ("1", "true", "yes"),
        state_dir=state_dir,
        tg_allowed_user_ids=allowed_user_ids,
        debug_dump_json=os.environ.get("DEBUG_DUMP_JSON", "").lower() in ("1", "true", "yes"),
        max_download_mb=_int_env("MAX_DOWNLOAD_MB", 50),
        tg_upload_mb=_int_env("TG_UPLOAD_MB", 50),
    )
