import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = _env_int("PARSERDOC_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
    default_encoding: str = os.environ.get("PARSERDOC_DEFAULT_ENCODING", "utf-8")
    request_timeout_seconds: int = _env_int("PARSERDOC_REQUEST_TIMEOUT_SECONDS", 120)


settings = Settings()

