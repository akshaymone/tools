"""
LLM Provider Factory (Standalone)
=================================
Single-file LLM factory — no external 'agents' package required.

Reads configuration directly from environment variables (loaded via python-dotenv).

Supported providers
-------------------
  "ollama"  — Local Ollama server (fully offline)
  "office"  — Office DevAssistant API (OpenAI-compatible endpoint)

Usage
-----
    from translator.llm_factory import get_llm

    llm = get_llm()                        # uses LLM_PROVIDER from .env
    llm = get_llm(provider="ollama")       # override at call time
"""
from __future__ import annotations

import base64
import logging
import os

from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)


def _build_office() -> BaseChatModel:
    """
    Office DevAssistant API — OpenAI-compatible endpoint.

    Auth strategy (in priority order):
      1. Bearer token  → OFFICE_API_KEY is set
      2. HTTP Basic    → OFFICE_USERNAME + OFFICE_PASSWORD are set
      3. No auth       → open endpoint (unlikely but handled)
    """
    from langchain_openai import ChatOpenAI
    import httpx

    office_base_url = os.getenv("OFFICE_BASE_URL", "http://localhost:8000")
    office_model = os.getenv("OFFICE_MODEL", "gpt-4o")
    office_api_key = os.getenv("OFFICE_API_KEY", "")
    office_username = os.getenv("OFFICE_USERNAME", "")
    office_password = os.getenv("OFFICE_PASSWORD", "")
    office_verify_ssl = os.getenv("OFFICE_VERIFY_SSL", "false").lower() in ("true", "1", "yes")
    llm_temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
    llm_max_tokens_str = os.getenv("LLM_MAX_TOKENS")
    llm_max_tokens = int(llm_max_tokens_str) if llm_max_tokens_str else None

    extra_headers: dict[str, str] = {}

    if office_api_key:
        api_key = office_api_key
        logger.debug("Office LLM: using Bearer token auth.")
    elif office_username and office_password:
        raw = f"{office_username}:{office_password}"
        encoded = base64.b64encode(raw.encode()).decode()
        extra_headers["Authorization"] = f"Basic {encoded}"
        api_key = "basic-auth"  # dummy — header override takes precedence
        logger.debug("Office LLM: using HTTP Basic auth.")
    else:
        api_key = "no-auth"
        logger.warning("Office LLM: no auth credentials configured. Requests may be rejected.")

    _base = office_base_url.rstrip("/")
    if not _base.endswith("/v1"):
        _base = f"{_base}/v1"

    http_client = httpx.Client(verify=office_verify_ssl)

    llm = ChatOpenAI(
        base_url=_base,
        api_key=api_key,
        model=office_model,
        temperature=llm_temperature,
        model_kwargs={"extra_body": {"max_tokens": llm_max_tokens}} if llm_max_tokens else {},
        default_headers=extra_headers if extra_headers else None,
        http_client=http_client,
    )
    logger.info("LLM → office (%s) @ %s/chat/completions", office_model, _base)
    return llm


def _build_ollama() -> BaseChatModel:
    """Local Ollama server — fully offline, great for personal data."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError as e:
        raise ImportError(
            "langchain-ollama is not installed. "
            "Run: pip install langchain-ollama"
        ) from e

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.getenv("OLLAMA_MODEL", "gemma3:12b")
    num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "32768"))
    num_predict = int(os.getenv("OLLAMA_NUM_PREDICT", "2048"))

    llm = ChatOllama(
        base_url=base_url,
        model=model,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )
    logger.info(
        "LLM → ollama (%s) @ %s  [num_ctx=%d, num_predict=%d]",
        model, base_url, num_ctx, num_predict,
    )
    return llm


_BUILDERS = {
    "office": _build_office,
    "ollama": _build_ollama,
}


def get_llm(provider: str | None = None, **kwargs) -> BaseChatModel:
    """
    Return a configured BaseChatModel for the given provider.

    Parameters
    ----------
    provider:
        One of "office", "ollama".
        Defaults to LLM_PROVIDER env var (fallback: "ollama").
    **kwargs:
        Optional overrides forwarded via llm.bind(**kwargs).

    Returns
    -------
    BaseChatModel — ready to .invoke().
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "ollama")).lower().strip()

    if provider not in _BUILDERS:
        available = ", ".join(_BUILDERS.keys())
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Available providers: {available}"
        )

    llm = _BUILDERS[provider]()

    if kwargs:
        llm = llm.bind(**kwargs)

    return llm
