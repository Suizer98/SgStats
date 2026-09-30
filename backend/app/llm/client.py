"""OpenAI-compatible chat client used by the agents.

The base URL is whatever gateway is configured (Bifrost in this deployment).
Prompts and output schemas stay in the agent that needs them.
"""

from __future__ import annotations

import time
from contextvars import ContextVar

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.constants import PROVIDER_ORDER
from app.core import settings


class LLMError(Exception):
    pass


calledProviders: ContextVar[list[str] | None] = ContextVar("calledProviders", default=None)


def begin_providers() -> None:
    calledProviders.set([])


def note_provider(name: str) -> None:
    current = calledProviders.get()
    if current is None or name not in PROVIDER_ORDER or name in current:
        return
    current.append(name)


def providers_used() -> list[str]:
    current = calledProviders.get() or []
    return [name for name in PROVIDER_ORDER if name in current]


def gateway_base() -> str:
    url = settings.BIFROST_URL.rstrip("/")
    if url.endswith("/v1"):
        return url
    return f"{url}/v1"


def make_chat_model(
    timeout: float | None = None,
    models: list[str] | None = None,
    max_tokens: int | None = None,
) -> BaseChatModel | None:
    if not settings.BIFROST_URL:
        return None
    chosen = models if models is not None else settings.chat_model_ids()
    if not chosen:
        return None
    kwargs: dict = {}
    if len(chosen) > 1:
        kwargs["extra_body"] = {"fallbacks": chosen[1:]}
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    return ChatOpenAI(
        model=chosen[0],
        base_url=gateway_base(),
        api_key=settings.LLM_API_KEY,
        temperature=0.2,
        timeout=timeout,
        max_retries=0 if timeout else 2,
        **kwargs,
    )


def provider_name(message: AIMessage) -> str:
    meta = message.response_metadata or {}
    model = str(meta.get("model_name") or meta.get("model") or "").lower()
    gemini_id = settings.GEMINI_MODEL.lower()
    groq_id = settings.GROQ_MODEL.lower()
    if "gemini" in model or (gemini_id and gemini_id in model):
        return "gemini"
    if "groq" in model or (groq_id and groq_id in model):
        return "groq"
    return "gateway"


def complete(
    system: str,
    human: str,
    schema: type[BaseModel],
    variables: dict,
    timeout: float | None = None,
    models: list[str] | None = None,
    max_tokens: int | None = None,
) -> dict:
    kwargs = {}
    if models is not None:
        kwargs["models"] = models
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    model = make_chat_model(timeout, **kwargs)
    if model is None:
        raise LLMError("No LLM gateway URL set")
    parser = PydanticOutputParser(pydantic_object=schema)
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", "{system_prompt}\n{format_instructions}"),
            ("human", human),
        ]
    ).partial(format_instructions=parser.get_format_instructions(), system_prompt=system)
    started = time.perf_counter()
    message = (prompt | model).invoke(variables)
    if not isinstance(message, AIMessage):
        raise LLMError("LangChain returned a non-chat message")
    content = message.content if isinstance(message.content, str) else str(message.content)
    usage = message.usage_metadata or {}
    provider = provider_name(message)
    note_provider(provider)
    return {
        "body": parser.parse(content).model_dump(),
        "provider": provider,
        "usage": {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
            "seconds": round(time.perf_counter() - started, 2),
        },
    }
