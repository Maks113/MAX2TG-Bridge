import os
from dataclasses import dataclass

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    max_token: str
    max_device_id: str
    tg_bot_token: str
    tg_chat_id: str
    max_chat_ids: str | None = None
    tg_proxy: str | None = None
    debug: bool = False
    reply_enabled: bool = False
    state_dir: str = "state"
    tg_allowed_user_ids: frozenset[int] | None = None
    debug_dump_json: bool = False
    max_download_mb: int = 50
    tg_upload_mb: int = 50


def load_settings() -> Settings:
    load_dotenv()

    required = ["MAX_TOKEN", "MAX_DEVICE_ID", "TG_BOT_TOKEN", "TG_CHAT_ID"]
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

    return Settings(
        max_token=os.environ["MAX_TOKEN"],
        max_device_id=os.environ["MAX_DEVICE_ID"],
        tg_bot_token=os.environ["TG_BOT_TOKEN"],
        tg_chat_id=tg_chat_id,
        max_chat_ids=os.environ.get("MAX_CHAT_IDS") or None,
        tg_proxy=os.environ.get("TG_PROXY") or None,
        debug=os.environ.get("DEBUG", "").lower() in ("1", "true", "yes"),
        reply_enabled=os.environ.get("REPLY_ENABLED", "").lower() in ("1", "true", "yes"),
        state_dir=os.environ.get("STATE_DIR") or "state",
        tg_allowed_user_ids=allowed_user_ids,
        debug_dump_json=os.environ.get("DEBUG_DUMP_JSON", "").lower() in ("1", "true", "yes"),
        max_download_mb=_int_env("MAX_DOWNLOAD_MB", 50),
        tg_upload_mb=_int_env("TG_UPLOAD_MB", 50),
    )
