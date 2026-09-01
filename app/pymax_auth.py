import logging

from app.config import Settings

log = logging.getLogger(__name__)


class EnvPasswordProvider:
    def __init__(self, password: str):
        self._password = password

    async def get_password(self, hint: str | None = None) -> str:
        return self._password


class LoggingQrHandler:
    async def show_qr(self, qr_url: str) -> None:
        log.warning("PyMax QR authorization URL: %s", qr_url)


def build_pymax_client(settings: Settings):
    """Build a PyMax client for the configured primary auth flow.

    PyMax is an optional dependency while the legacy MAX client remains the
    default, so imports stay local to this factory.
    """
    try:
        from pymax import Client, ExtraConfig, WebClient
    except ImportError as exc:
        raise RuntimeError(
            "MAX_CLIENT_BACKEND=pymax requires maxapi-python to be installed."
        ) from exc

    extra_config = ExtraConfig(
        proxy=settings.tg_proxy,
        log_level="DEBUG" if settings.debug else "INFO",
    )

    if settings.max_pymax_auth == "qr":
        return WebClient(
            work_dir=settings.max_pymax_work_dir,
            session_name=settings.max_pymax_session_name,
            extra_config=extra_config,
            qr_provider=LoggingQrHandler(),
        )

    if not settings.max_phone:
        raise RuntimeError("MAX_PYMAX_AUTH=sms requires MAX_PHONE.")

    password_provider = (
        EnvPasswordProvider(settings.max_2fa_password)
        if settings.max_2fa_password
        else None
    )
    return Client(
        phone=settings.max_phone,
        work_dir=settings.max_pymax_work_dir,
        session_name=settings.max_pymax_session_name,
        extra_config=extra_config,
        password_provider=password_provider,
    )
