"""Configuration helpers for my-ime."""

from __future__ import annotations

import os


def env(name: str, default: str = "") -> str:
    """Return a MY_IME_* value, falling back to the old LLM_IME_* name."""

    return os.getenv(f"MY_IME_{name}", os.getenv(f"LLM_IME_{name}", default))
