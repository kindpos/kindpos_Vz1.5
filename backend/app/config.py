"""
KINDpos Configuration

Central configuration management using environment variables.
"""

from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "KINDpos"
    app_version: str = "0.1.0"
    debug: bool = True

    # Terminal identification
    terminal_id: str = "terminal_01"

    # Database
    database_path: str = "./data/event_ledger.db"

    # Server
    host: str = "127.0.0.1"
    port: int = 8000

    # Tax rate (0 until configured via Overseer)
    tax_rate: float = 0.0

    # Cash dual-pricing discount (0 until configured via Overseer)
    cash_discount_rate: float = 0.0

    # Tip-out percentage (default 2%)
    tipout_percent: float = 2.0

    # Store mode: "demo" seeds sample data, "production" starts clean
    store_mode: str = "demo"

    # Hardware Discovery
    default_subnet: str = "10.0.0.0/24"
    scan_timeout: float = 2.0

    # Financial invariants. When True, aggregation paths raise
    # InvariantViolation if any P&L / tender / tips identity drifts
    # outside tolerance. When False (production default), the mismatch
    # is logged at WARN level and a `reconciliation_diff` field is
    # surfaced on the response so operators can see the drift without
    # the API call failing. pytest flips this to True via conftest.
    strict_invariants: bool = False

    class Config:
        env_file = ".env"
        env_prefix = "KINDPOS_"


# Global settings instance
settings = Settings()
