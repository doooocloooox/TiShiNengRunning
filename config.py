from __future__ import annotations

import os
from dataclasses import dataclass


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./tsn_data.db")
    api_base_url: str = os.getenv("TSN_API_BASE_URL", "https://m.boxkj.com")
    cloud_base_url: str = os.getenv("TSN_CLOUD_BASE_URL", "http://a.sxstczx.com")
    connect_timeout: float = _float_env("TSN_CONNECT_TIMEOUT", 10.0)
    read_timeout: float = _float_env("TSN_READ_TIMEOUT", 30.0)
    write_timeout: float = _float_env("TSN_WRITE_TIMEOUT", 30.0)
    pool_timeout: float = _float_env("TSN_POOL_TIMEOUT", 10.0)

    @property
    def http_timeout(self):
        import httpx
        return httpx.Timeout(connect=self.connect_timeout, read=self.read_timeout, write=self.write_timeout, pool=self.pool_timeout)


settings = Settings()
