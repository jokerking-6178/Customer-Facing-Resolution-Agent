"""Environment configuration.

Loads the repo-root `.env` once, at import time, before any other module
reads `os.getenv()`. Without this the file is inert: a GROQ_API_KEY sitting
in `.env` is never seen and the app silently falls back to its default
provider.

Real environment variables win over `.env` (python-dotenv does not override
by default), so `$env:LLM_PROVIDER = "mock"` or a Render dashboard value
still takes precedence over the local file.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def load_env() -> bool:
    """Load the repo-root .env. Returns True if a file was found."""
    try:
        from dotenv import load_dotenv
    except ImportError:  # dotenv is optional; env vars still work without it
        return False
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=False)
        return True
    return False


LOADED_ENV = load_env()


def provider_name() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").lower()
