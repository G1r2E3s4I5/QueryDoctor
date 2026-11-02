# backend/app/config.py
"""
Configuration module for QueryDoctor backend.
Loads environment variables with sensible defaults using python-dotenv.
Only loads values; does not establish any DB connections.
"""

import os
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*args, **kwargs):
        """Fallback no‑op when python‑dotenv is not installed."""
        return None

# Load .env file if present (searches parent directories)
ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH)

# Application settings
APP_ENV = os.getenv("APP_ENV", "development")
APP_HOST = os.getenv("APP_HOST", "127.0.0.1")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
TARGET_DATABASE_URL = os.getenv("TARGET_DATABASE_URL", "postgresql://user:password@localhost:5432/target_db")
PROJECT_DATABASE_URL = os.getenv("PROJECT_DATABASE_URL", "postgresql://user:password@localhost:5432/project_db")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")


# Configuration variables for the backend.
