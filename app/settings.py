from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    max_upload_bytes: int = 20 * 1024 * 1024
    default_encoding: str = "utf-8"
    request_timeout_seconds: int = 120


settings = Settings()

