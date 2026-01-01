"""Configuration settings for Sophia Arithmos."""

import logging
import sys

from pydantic_settings import BaseSettings, SettingsConfigDict


class LoggingSettings(BaseSettings):
    """Logging configuration."""

    level: str = "INFO"
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format: str = "%Y-%m-%d %H:%M:%S"


class PrecisionSettings(BaseSettings):
    """Decimal precision settings for different data types."""

    rate: int = 4           # Interest rates: 3.4567%
    percent: int = 2        # Percentages: 2.75%
    index: int = 2          # Index values: 4532.21
    ratio: int = 6          # Ratios: 0.123456
    currency: int = 2       # Dollar amounts: 1234.56
    default: int = 4        # Fallback precision


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ARITHMOS_",
        case_sensitive=False,
    )

    # Server settings
    host: str = "0.0.0.0"
    port: int = 8001
    debug: bool = False

    # Computation settings
    max_input_points: int = 10000       # Maximum observations per request
    max_computations: int = 20          # Maximum computations per request
    default_output: str = "latest"      # "full" | "latest" | "summary"

    # Precision settings (nested)
    precision: PrecisionSettings = PrecisionSettings()

    # Logging settings (nested)
    logging: LoggingSettings = LoggingSettings()


settings = Settings()


def configure_logging() -> None:
    """Configure application-wide logging."""
    log_level = getattr(logging, settings.logging.level.upper(), logging.INFO)

    # Configure root logger for sophia_arithmos
    logger = logging.getLogger("sophia_arithmos")
    logger.setLevel(log_level)

    # Avoid duplicate handlers
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(log_level)
        formatter = logging.Formatter(
            settings.logging.format,
            datefmt=settings.logging.date_format,
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    # Prevent propagation to root logger to avoid duplicate logs
    logger.propagate = False
