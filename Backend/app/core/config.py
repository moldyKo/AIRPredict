import os
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = os.path.dirname(
    os.path.dirname(
        os.path.dirname(os.path.abspath(__file__))
    )
)

ENV_FILE_PATH = os.path.join(BASE_DIR, ".env")


class Settings(BaseSettings):
    PROJECT_NAME: str = "AIRPredict"
    API_V1_STR: str = "/api/v1"

    DATABASE_URL: str = Field(
        validation_alias="DATABASE_URL"
    )

    OPENAQ_API_KEY: str = Field(
        default="",
        validation_alias="OPENAQ_API_KEY"
    )

    OPENWEATHER_API_KEY: str = Field(
        default="",
        validation_alias="OPENWEATHER_API_KEY"
    )

    WAQI_API_KEY: str = Field(
        default="",
        validation_alias="WAQI_API_KEY"
    )

    REDIS_URL: str = Field(
        default="redis://localhost:6379/0",
        validation_alias="REDIS_URL"
    )

    SCHEDULER_ENABLED: bool = Field(
        default=True,
        validation_alias="SCHEDULER_ENABLED"
    )

    INGESTION_INTERVAL_MINUTES: int = Field(
        default=10,
        validation_alias="INGESTION_INTERVAL_MINUTES"
    )

    NEAREST_STATION_RADIUS_KM: float = 50.0

    ACTIVE_STATION_HOURS: int = 24

    ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )


settings = Settings()