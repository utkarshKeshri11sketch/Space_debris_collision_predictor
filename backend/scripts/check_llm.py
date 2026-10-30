"""Smoke-test each free LLM provider: python scripts/check_llm.py

Makes one tiny call per provider that has a key in the environment (GROQ_API_KEY, GEMINI_API_KEY,
CEREBRAS_API_KEY) and prints OK/FAIL with latency. Keys are never printed.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai import llm  # noqa: E402

PROMPT = [{"role": "user", "content": "Reply with exactly: pong"}]


def main() -> int:
    ok_any = False
    for name, (_, key_env, _, _) in llm._OPENAI_COMPAT.items():
        if not os.environ.get(key_env):
            print(f"{name:9s} SKIP  ({key_env} not set)")
            continue
        start = time.perf_counter()
        try:
            text = llm._live_complete(name, "You are a connectivity test.", PROMPT, False, 16)
            print(f"{name:9s} OK    {time.perf_counter() - start:.2f}s  model={llm._model(name)}  reply={text[:30]!r}")
            ok_any = True
        except Exception as exc:  # noqa: BLE001
            print(f"{name:9s} FAIL  {time.perf_counter() - start:.2f}s  {type(exc).__name__}: {str(exc)[:200]}")
    return 0 if ok_any else 1


if __name__ == "__main__":
    raise SystemExit(main())
