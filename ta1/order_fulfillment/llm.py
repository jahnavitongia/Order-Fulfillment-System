from typing import Optional
import os


def call_local_llm(prompt: str, model: Optional[str] = None) -> Optional[str]:
    """Call local Ollama server using model from env or provided param.

    Returns the generated text or None on failure. Sets `OLLAMA_HOST` from
    environment if present so the Python client uses the correct server.
    """
    # Respect explicit model arg, then OLLAMA_MODEL env var, then default
    model = model or os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")

    # If user set OLLAMA_HOST, ensure it's in env for the client library
    host = os.environ.get("OLLAMA_HOST")
    if host:
        os.environ["OLLAMA_HOST"] = host

    try:
        import ollama
        resp = ollama.chat(
            model=model,
            messages=[{"role": "user", "content": prompt}],
        )
        return resp["message"]["content"].strip()
    except Exception as e:
        # Lightweight debug info; caller will fall back to deterministic templates
        print(f"[order_fulfillment.llm] Ollama call failed: {e}")
        return None

