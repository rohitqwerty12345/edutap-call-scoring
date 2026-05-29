import os
from typing import Any, Dict


def get_setting(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value not in (None, ""):
        return value
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return default


def _as_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    if obj is None:
        return {}
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump()
        except Exception:
            pass
    if hasattr(obj, "to_dict"):
        try:
            return obj.to_dict()
        except Exception:
            pass
    if hasattr(obj, "__dict__"):
        return {k: v for k, v in obj.__dict__.items() if not k.startswith("_")}
    return {}


def _float_setting(name: str, default: float) -> float:
    raw = get_setting(name)
    if raw in (None, ""):
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _default_openai_prices(model: str) -> Dict[str, float]:
    """Fallback standard prices per 1M tokens. Override through secrets whenever pricing changes."""
    m = (model or "").lower()
    if "5.4 mini" in m or "5-4-mini" in m or "5.4-mini" in m:
        return {"input": 0.75, "cached_input": 0.075, "output": 4.50}
    if "5.4" in m or "5-4" in m:
        return {"input": 2.50, "cached_input": 0.25, "output": 15.00}
    # Production default used by this app.
    return {"input": 5.00, "cached_input": 0.50, "output": 30.00}


def current_openai_prices(model: str) -> Dict[str, float]:
    defaults = _default_openai_prices(model)
    return {
        "input": _float_setting("OPENAI_INPUT_PRICE_PER_1M", defaults["input"]),
        "cached_input": _float_setting("OPENAI_CACHED_INPUT_PRICE_PER_1M", defaults["cached_input"]),
        "output": _float_setting("OPENAI_OUTPUT_PRICE_PER_1M", defaults["output"]),
    }


def batch_discount_multiplier(processing_mode: str) -> float:
    """Batch API is normally 50% cost, represented as multiplier 0.5. Override if needed."""
    if (processing_mode or "standard").strip().lower() != "batch":
        return 1.0
    return _float_setting("OPENAI_BATCH_DISCOUNT", 0.5)


def extract_openai_usage(response_or_body: Any) -> Dict[str, int]:
    data = _as_dict(response_or_body)
    usage = data.get("usage")
    if usage is None and hasattr(response_or_body, "usage"):
        usage = getattr(response_or_body, "usage", None)
    usage_dict = _as_dict(usage)

    def as_int(value: Any) -> int:
        try:
            return int(value or 0)
        except Exception:
            return 0

    input_tokens = as_int(usage_dict.get("input_tokens") or usage_dict.get("prompt_tokens"))
    output_tokens = as_int(usage_dict.get("output_tokens") or usage_dict.get("completion_tokens"))
    total_tokens = as_int(usage_dict.get("total_tokens")) or input_tokens + output_tokens

    details = _as_dict(
        usage_dict.get("input_tokens_details")
        or usage_dict.get("prompt_tokens_details")
        or usage_dict.get("input_details")
    )
    cached_input_tokens = as_int(
        details.get("cached_tokens")
        or details.get("cached_input_tokens")
        or details.get("cache_read_input_tokens")
    )
    cached_input_tokens = min(cached_input_tokens, input_tokens) if input_tokens else cached_input_tokens

    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "billable_input_tokens": max(input_tokens - cached_input_tokens, 0),
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def calculate_openai_cost(usage: Dict[str, int], model: str, processing_mode: str = "standard") -> Dict[str, Any]:
    prices = current_openai_prices(model)
    multiplier = batch_discount_multiplier(processing_mode)

    billable_input_tokens = int(usage.get("billable_input_tokens") or 0)
    cached_input_tokens = int(usage.get("cached_input_tokens") or 0)
    output_tokens = int(usage.get("output_tokens") or 0)

    input_cost = (billable_input_tokens / 1_000_000) * prices["input"] * multiplier
    cached_input_cost = (cached_input_tokens / 1_000_000) * prices["cached_input"] * multiplier
    output_cost = (output_tokens / 1_000_000) * prices["output"] * multiplier
    total = input_cost + cached_input_cost + output_cost

    return {
        **usage,
        "openai_model": model,
        "processing_mode": processing_mode,
        "openai_input_price_per_1m": prices["input"],
        "openai_cached_input_price_per_1m": prices["cached_input"],
        "openai_output_price_per_1m": prices["output"],
        "openai_batch_discount_multiplier": multiplier,
        "openai_input_cost_usd": round(input_cost, 8),
        "openai_cached_input_cost_usd": round(cached_input_cost, 8),
        "openai_output_cost_usd": round(output_cost, 8),
        "openai_total_cost_usd": round(total, 8),
        "total_cost_usd": round(total, 8),
    }


def merge_cost_parts(*parts: Dict[str, Any] | None) -> Dict[str, Any]:
    merged: Dict[str, Any] = {}
    for part in parts:
        if isinstance(part, dict):
            merged.update(part)
    merged["total_cost_usd"] = round(float(merged.get("openai_total_cost_usd") or 0.0), 8)
    return merged


def usd(value: Any) -> str:
    try:
        return f"${float(value or 0):.6f}"
    except Exception:
        return "$0.000000"
