"""Demo-mode and access-gate policy (pure functions, no streamlit, no heavy imports).

Demo mode = a public, read-only deployment: saved results only, no SEC / Claude / Jev calls, no watchlist database.

FFA_DEMO_MODE: 1/true/yes/on => demo; 0/false/no/off => live; unset/anything else => "auto": demo unless a real
SEC_USER_AGENT is configured (set, not a placeholder such as 'your@email' / 'example.com').
Values are read from os.environ first, then from the repo's .env (FFA_ENV_FILE overrides the path; used by tests).
The .env is parsed here with a tiny reader that only looks up the requested key, so tools.common is never imported.
"""
from __future__ import annotations

import hmac
import os
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
TRUE = {"1", "true", "yes", "on"}
FALSE = {"0", "false", "no", "off"}
PLACEHOLDER_MARKERS = ("your@email", "your-real@email", "example.com", "example.org", "yourapp", "your-email", "changeme", "placeholder")


def _env_file() -> Path:
    return Path(os.environ.get("FFA_ENV_FILE") or (ROOT / ".env"))


def get_setting(name: str) -> Optional[str]:
    """os.environ[name], else the value in the .env file, else None. Never logs or prints values."""
    v = os.environ.get(name)
    if v is not None and v.strip():
        return v.strip()
    try:
        p = _env_file()
        if not p.is_file():
            return None
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, _, val = s.partition("=")
            k = k.strip()
            if k.lower().startswith("export "):
                k = k[7:].strip()
            if k == name:
                val = val.strip()
                if val[:1] in "\"'" and val[-1:] == val[:1] and len(val) >= 2:
                    val = val[1:-1]
                return val.strip() or None
    except OSError:
        return None
    return None


def is_placeholder_ua(ua: Optional[str]) -> bool:
    if not ua or not ua.strip():
        return True
    low = ua.strip().lower()
    if any(m in low for m in PLACEHOLDER_MARKERS):
        return True
    return "@" not in low  # the SEC wants 'AppName contact-email'


def demo_mode() -> bool:
    raw = (os.environ.get("FFA_DEMO_MODE") or "").strip().lower()
    if raw in TRUE:
        return True
    if raw in FALSE:
        return False
    return is_placeholder_ua(get_setting("SEC_USER_AGENT"))  # auto


def access_code() -> Optional[str]:
    """The configured live-mode access code, or None (=> no gate). Only meaningful when demo mode is off."""
    return get_setting("FFA_ACCESS_CODE")


def check_code(supplied: str, expected: Optional[str]) -> bool:
    if not expected:
        return True
    return hmac.compare_digest((supplied or "").encode("utf-8"), expected.encode("utf-8"))
