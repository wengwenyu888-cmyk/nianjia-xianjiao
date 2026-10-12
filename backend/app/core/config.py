"""全局配置：pydantic-settings 从环境变量 / .env 读取，启动期即校验。

原则：镜像内不烘焙任何环境差异，一切配置走环境变量（见 docs/05 安全要点）。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

Env = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class Settings(BaseSettings):
    """集中所有配置项；新增配置只允许加在这里，禁止各模块自行读 env。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- 应用 ----------
    APP_NAME: str = "念家鲜饺供应链系统"
    VERSION: str = "0.1.0"
    ENV: Env = "dev"
    DEBUG: bool = False
    LOG_LEVEL: LogLevel = "INFO"
    API_V1_PREFIX: str = "/api/v1"

    # ---------- 数据库 ----------
    # 同步链路使用 PyMySQL（纯 Python 驱动，容器内免编译）
    # MySQL 8 的 caching_sha2_password 认证需要 cryptography
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "nianjia"
    DB_PASSWORD: str = ""
    DB_NAME: str = "nianjia_xianjiao"
    DB_CHARSET: str = "utf8mb4"
    DB_POOL_SIZE: int = 5
    DB_MAX_OVERFLOW: int = 10
    DB_ECHO: bool = False
    DATABASE_URL: str | None = None  # 显式给出时优先，便于 CI / 测试注入

    # ---------- JWT ----------
    JWT_SECRET_KEY: str = "dev-only-secret-change-me-0123456789abcdef"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 120  # access token 短有效期（约 2 小时）
    REFRESH_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # refresh token 7 天

    # ---------- CORS ----------
    CORS_ORIGINS: list[str] = Field(
        default_factory=lambda: ["http://127.0.0.1:5173", "http://localhost:5173"]
    )

    # ---------- 限流 ----------
    RATE_LIMIT_DEFAULT: str = "120/minute"

    # ---------- 外部集成（银豹 / 金蝶 / 管家婆 / LLM，二期启用）----------
    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.deepseek.com/v1"
    LLM_MODEL: str = "deepseek-chat"

    # ---------- 派生属性 ----------
    @property
    def is_dev(self) -> bool:
        return self.ENV == "dev"

    @property
    def is_prod(self) -> bool:
        return self.ENV == "prod"

    @property
    def database_url(self) -> str:
        """SQLAlchemy 同步连接串；显式 DATABASE_URL 优先。"""
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            "mysql+pymysql://"
            f"{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset={self.DB_CHARSET}"
        )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        """允许用逗号分隔的字符串写白名单（.env 里更顺手）。"""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("JWT_SECRET_KEY")
    @classmethod
    def _check_secret(cls, value: str) -> str:
        """HS256 密钥至少 32 字节，不达标直接拒绝启动（错误在启动期暴露）。"""
        if len(value.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY 长度不足 32 字节，请用 openssl rand -hex 32 生成")
        return value


@lru_cache
def get_settings() -> Settings:
    """带缓存的配置单例；测试中改环境变量后需 get_settings.cache_clear()。"""
    return Settings()


settings = get_settings()
