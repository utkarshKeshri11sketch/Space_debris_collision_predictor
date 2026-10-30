"""Environment-driven configuration. No secrets live in code; see app/ai/README.md for the variables."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class AiConfig:
    # "auto" tries bedrock, then gemini, then falls back to deterministic templates.
    provider: str = "auto"
    # Long-standing, cheap Bedrock model id; override with BEDROCK_MODEL_ID for newer models.
    bedrock_model_id: str = "anthropic.claude-3-haiku-20240307-v1:0"
    bedrock_region: str = "us-east-1"
    gemini_model: str = "gemini-1.5-flash"
    gemini_api_key: str = ""
    max_tokens: int = 400
    timeout_s: float = 20.0
    # After a provider fails, skip it for this long so a dead provider cannot stall every call.
    cooldown_s: float = 60.0
    # Optional directory for the record/replay response cache ("" disables disk caching).
    cache_dir: str = ""
    # Whether conjunction briefs call the LLM (costs credits) or use templates.
    brief_mode: str = "template"  # "template" | "llm"

    @classmethod
    def from_env(cls) -> "AiConfig":
        env = os.environ.get
        return cls(
            provider=env("AI_PROVIDER", cls.provider).lower(),
            bedrock_model_id=env("BEDROCK_MODEL_ID", cls.bedrock_model_id),
            bedrock_region=env("BEDROCK_REGION", env("AWS_REGION", cls.bedrock_region)),
            gemini_model=env("GEMINI_MODEL", cls.gemini_model),
            gemini_api_key=env("GEMINI_API_KEY", ""),
            max_tokens=int(env("AI_MAX_TOKENS", cls.max_tokens)),
            timeout_s=float(env("AI_TIMEOUT_S", cls.timeout_s)),
            cooldown_s=float(env("AI_COOLDOWN_S", cls.cooldown_s)),
            cache_dir=env("AI_CACHE_DIR", ""),
            brief_mode=env("AI_BRIEF_MODE", cls.brief_mode).lower(),
        )
