"""Claude access for forensic-filing-agent (Haiku for extraction, Sonnet for synthesis).

All functions are deterministic where possible (temperature 0, sha256-keyed disk cache under
``.cache/llm/``) and NEVER raise: any failure or missing ``ANTHROPIC_API_KEY`` yields ``None``.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any, Optional

from tools import common
from tools.common import MODEL_HAIKU, MODEL_SONNET, get_logger

log = get_logger("llm")

# Corporate networks often use TLS-inspecting proxies whose CA lives in the OS trust store, not in certifi: without
# this the Anthropic client fails with APIConnectionError (found in the first live run; tools.edgar_api does the same
# for SEC calls). Harmless when truststore is absent.
try:  # pragma: no cover - environment dependent
    import truststore

    truststore.inject_into_ssl()
except Exception:  # noqa: BLE001
    pass

_cache_lock = threading.Lock()
_MAX_RETRIES = 2
_NO_TEMPERATURE_MODELS: set = set()


def llm_available() -> bool:
    """True when ``ANTHROPIC_API_KEY`` is set (non-empty, not the .env.example placeholder)."""
    common.load_env()
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    return bool(key) and key != "your_anthropic_api_key"


def _model_for(tier: str) -> str:
    return MODEL_SONNET if str(tier).lower() == "sonnet" else MODEL_HAIKU


def _cache_path(model: str, system: str, user: str, kind: str, max_tokens: int) -> Path:
    digest = hashlib.sha256("\x1f".join([kind, model, system, user, str(max_tokens)]).encode("utf-8")).hexdigest()
    return common.CACHE_DIR / "llm" / f"{digest}.json"


def _cache_read(path: Path) -> Optional[Any]:
    try:
        with _cache_lock:
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8")).get("response")
    except Exception:
        return None
    return None


def _cache_write(path: Path, response: Any, model: str) -> None:
    try:
        with _cache_lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"model": model, "response": response}, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
    except Exception as exc:  # pragma: no cover
        log.debug("llm cache write failed: %s", exc)


def _call_model(model: str, system: str, user: str, max_tokens: int) -> Optional[str]:
    """One Claude call through ``langchain_anthropic.ChatAnthropic`` (temperature 0)."""
    from langchain_anthropic import ChatAnthropic

    # Newer models (e.g. Sonnet 5.5) reject `temperature` ("deprecated for this model"); Haiku accepts it. Try with
    # temperature 0 first and drop it for models that refuse; reproducibility comes from the disk cache either way.
    kwargs = dict(model=model, max_tokens=max_tokens, timeout=90, max_retries=1)
    if model not in _NO_TEMPERATURE_MODELS:
        kwargs["temperature"] = 0
    try:
        msg = ChatAnthropic(**kwargs).invoke([("system", system), ("human", user)])
    except Exception as exc:
        if "temperature" in str(exc).lower() and "temperature" in kwargs:
            _NO_TEMPERATURE_MODELS.add(model)
            kwargs.pop("temperature")
            msg = ChatAnthropic(**kwargs).invoke([("system", system), ("human", user)])
        else:
            raise
    content = msg.content
    if isinstance(content, list):
        content = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content)


def _parse_json(text: str) -> Optional[dict]:
    """Parse a JSON object from model output, repairing code fences, surrounding prose and trailing commas."""
    if not text:
        return None
    s = text.strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", s, re.DOTALL | re.IGNORECASE)
    if fence:
        s = fence.group(1).strip()
    candidates = [s]
    first, last = s.find("{"), s.rfind("}")
    if first != -1 and last > first:
        candidates.append(s[first:last + 1])
    for cand in candidates:
        for variant in (cand, re.sub(r",\s*([}\]])", r"\1", cand)):
            try:
                obj = json.loads(variant)
            except (ValueError, TypeError):
                continue
            if isinstance(obj, dict):
                return obj
    return None


def llm_json(tier: str, system: str, user: str, *, max_tokens: int = 800) -> Optional[dict]:
    """Ask Claude for a JSON object. Returns a dict or None (no key, API failure, unparsable). Never raises.

    ``tier`` is ``"haiku"`` or ``"sonnet"``. Results are cached on disk by sha256(model+system+user),
    so re-runs are deterministic (a cache hit works even without an API key).
    """
    try:
        model = _model_for(tier)
        path = _cache_path(model, system, user, "json", max_tokens)
        cached = _cache_read(path)
        if isinstance(cached, dict):
            return cached
        if not llm_available():
            return None
        sys_prompt = system + "\n\nRespond with a single valid JSON object and nothing else."
        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw = _call_model(model, sys_prompt, user, max_tokens)
            except Exception as exc:
                log.warning("llm_json attempt %d failed: %s", attempt + 1, type(exc).__name__)
                continue
            obj = _parse_json(raw or "")
            if obj is not None:
                _cache_write(path, obj, model)
                return obj
        return None
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("llm_json error: %s", exc)
        return None


def llm_text(tier: str, system: str, user: str, max_tokens: int = 1500) -> Optional[str]:
    """Ask Claude for free text. Returns the string or None. Never raises. Disk-cached like :func:`llm_json`."""
    try:
        model = _model_for(tier)
        path = _cache_path(model, system, user, "text", max_tokens)
        cached = _cache_read(path)
        if isinstance(cached, str):
            return cached
        if not llm_available():
            return None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                raw = _call_model(model, system, user, max_tokens)
            except Exception as exc:
                log.warning("llm_text attempt %d failed: %s", attempt + 1, type(exc).__name__)
                continue
            if raw and raw.strip():
                _cache_write(path, raw.strip(), model)
                return raw.strip()
        return None
    except Exception as exc:  # pragma: no cover
        log.warning("llm_text error: %s", exc)
        return None
