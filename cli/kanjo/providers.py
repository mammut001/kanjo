"""Provider mapping for public usage summaries (CONTRACT.md section 12).

Maps model names (and single-vendor agent fallbacks) to provider keys and labels.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

PROVIDER_LABELS: Dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "google": "Google",
    "xai": "xAI",
    "alibaba": "Alibaba (Qwen)",
    "minimax": "MiniMax",
    "moonshot": "Moonshot (Kimi)",
    "deepseek": "DeepSeek",
    "zhipu": "Zhipu (GLM)",
    "stepfun": "StepFun",
    "meta": "Meta",
    "other": "Other",
}

# Rules are matched in order against the model name with any vendor/ prefix stripped.
PROVIDER_RULES: List[Tuple[str, re.Pattern]] = [
    ("anthropic", re.compile(r"^claude", re.IGNORECASE)),
    ("openai", re.compile(r"^(?:gpt-|chatgpt|codex|o[0-9])", re.IGNORECASE)),
    ("google", re.compile(r"^(?:gemini|gemma)", re.IGNORECASE)),
    ("xai", re.compile(r"^grok", re.IGNORECASE)),
    ("alibaba", re.compile(r"^(?:qwen|qwq)", re.IGNORECASE)),
    ("minimax", re.compile(r"^(?:minimax|abab)", re.IGNORECASE)),
    ("moonshot", re.compile(r"^(?:kimi|moonshot)", re.IGNORECASE)),
    ("deepseek", re.compile(r"^deepseek", re.IGNORECASE)),
    ("zhipu", re.compile(r"^(?:glm|chatglm)", re.IGNORECASE)),
    ("stepfun", re.compile(r"^step", re.IGNORECASE)),
    ("meta", re.compile(r"^(?:muse|llama)", re.IGNORECASE)),
]

# Single-vendor agents fallback to their provider when model cannot be identified.
# Multi-vendor agents (commandcode, opencode, copilot, pi, workbuddy, workbuddy_ai, qoderwork, qodercli, qodercli_cn) have no fallback.
AGENT_FALLBACK: Dict[str, str] = {
    "claude": "anthropic",
    "codex": "openai",
    "antigravity": "google",
    "grok": "xai",
    "grok_bot": "xai",
    "qwen": "alibaba",
    "qwenwork": "alibaba",
    "minimax": "minimax",
    "kimicode": "moonshot",
    "zcode": "zhipu",
    "musecode": "meta",
    "deepseek_harness": "deepseek",
}


def strip_vendor_prefix(model: str) -> str:
    """Strip vendor/ prefix if present (e.g. 'anthropic/claude-3' -> 'claude-3')."""
    model = model.strip()
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def provider_for(model: str, agent: str) -> str:
    """Identify the provider key for a given model and agent.

    Matches model name prefix (after stripping vendor/ prefix).
    Falls back to single-vendor agent if model does not match.
    Returns 'other' if unidentifiable.
    """
    if model and model != "<synthetic>":
        name = strip_vendor_prefix(model)
        for provider, pattern in PROVIDER_RULES:
            if pattern.search(name):
                return provider
    return AGENT_FALLBACK.get(agent, "other")
