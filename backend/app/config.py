from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MEDNEXA_", env_file=".env", extra="ignore")

    app_name: str = "MedNexa API"
    database_url: str = "postgresql+asyncpg://mednexa:mednexa@localhost:5434/mednexa"
    test_database_url: str = "postgresql+asyncpg://mednexa:mednexa@localhost:5434/mednexa_test"
    db_pool_size: int = 10
    db_max_overflow: int = 20
    db_echo: bool = False
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
