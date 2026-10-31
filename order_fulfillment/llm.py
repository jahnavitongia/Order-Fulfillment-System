"""Thin wrapper around the local Ollama server (qwen2.5:3b by default).

The LLM is used ONLY to phrase the customer message. All decisions
(stock check, routing, shipping price) are deterministic code.
Set ORDER_USE_LLM=0 to disable the LLM (used by the unit tests).
"""
from typing import Optional
import os

DEFAULT_MODEL = "qwen2.5:3b"


def model_name() -> str:
    return os.environ.get("OLLAMA_MODEL", DEFAULT_MODEL)


def call_local_llm(prompt: str, model: Optional[str] = None) -> Optional[str]:
    """Return generated text, or None if disabled / unavailable / empty."""
    if os.environ.get("ORDER_USE_LLM", "1") == "0":
        return None
    model = model or model_name()
    try:
        import ollama
        client = ollama.Client(host=os.environ.get("OLLAMA_HOST"), timeout=30)
        resp = client.chat(model=model, messages=[{"role": "user", "content": prompt}])
        text = resp["message"]["content"].strip()
        return text or None
    except Exception as e:  # server down, model missing, timeout ...
        print(f"[order_fulfillment.llm] Ollama call failed: {e}")
        return None
