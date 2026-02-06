from __future__ import annotations

import json
import os
import random
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from eidolon.config.settings import LLMSettings, get_settings
from eidolon.core.reasoning.memory import ConversationMemory

try:
    import litellm

    # Enable automatic dropping of unsupported parameters for model compatibility
    litellm.drop_params = True
    # Enable debug logging if EIDOLON_LLM_DEBUG env var is set
    if os.getenv("EIDOLON_LLM_DEBUG"):
        os.environ["LITELLM_LOG"] = "DEBUG"
except ImportError:  # pragma: no cover - dependency is optional in early phases
    litellm = None

T = TypeVar("T", bound=BaseModel)
LLM_ENV_KEYS = (
    "OPENAI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "COHERE_API_KEY",
    "MISTRAL_API_KEY",
    "GROQ_API_KEY",
    "TOGETHER_API_KEY",
    "OPENROUTER_API_KEY",
    "FIREWORKS_API_KEY",
    "GOOGLE_API_KEY",
)


def _env_has_llm_key() -> bool:
    return any(os.getenv(key) for key in LLM_ENV_KEYS)


class LiteLLMClient:
    """Thin wrapper around LiteLLM to enforce structured JSON outputs."""

    def __init__(self, settings: LLMSettings | None = None) -> None:
        self.settings = settings or get_settings().llm
        self.memory = ConversationMemory(max_tokens=self.settings.max_context_tokens)
        if litellm is not None:
            litellm.drop_params = True

    def is_available(self) -> bool:
        if litellm is None:
            return False
        return bool(self.settings.api_key or self.settings.api_base or _env_has_llm_key())

    def _is_rate_limit_error(self, error: Exception) -> bool:
        error_str = str(error).lower()
        error_type = type(error).__name__.lower()
        return (
            ("rate" in error_str and "limit" in error_str)
            or "ratelimit" in error_type
            or "429" in error_str
            or "too many requests" in error_str
        )

    def _retry_with_backoff(self, call_fn, max_retries: int | None = None):
        retries = max_retries if max_retries is not None else self.settings.max_retries
        base_delay = self.settings.retry_delay

        for attempt in range(retries + 1):
            try:
                return call_fn()
            except Exception as exc:
                if not self._is_rate_limit_error(exc) or attempt >= retries:
                    raise
                delay = base_delay * (2**attempt) + random.uniform(0, 1)
                time.sleep(delay)
        raise RuntimeError("Retry attempts exhausted")

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Send a chat completion request, optionally with tool definitions.

        Returns the raw response dict with 'choices' containing message and optional tool_calls.
        """
        if litellm is None:
            raise RuntimeError("litellm is not installed in this environment")

        completion_args: dict[str, Any] = {
            "model": self.settings.model,
            "messages": messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if self.settings.reasoning_effort:
            completion_args["reasoning_effort"] = self.settings.reasoning_effort
        if tools:
            completion_args["tools"] = tools
            completion_args["tool_choice"] = "auto"
        if self.settings.api_base:
            completion_args["api_base"] = self.settings.api_base
        if self.settings.api_key:
            completion_args["api_key"] = self.settings.api_key

        response = litellm.completion(**completion_args)
        return response

    def generate(
        self,
        system_prompt: str,
        messages: list[dict[str, Any]],
        tools: list[Any] | None = None,
        memory: ConversationMemory | None = None,
    ) -> LLMResponse:
        """Generate a response with optional tool calling support."""
        if litellm is None:
            raise RuntimeError("litellm is not installed in this environment")

        llm_messages = [{"role": "system", "content": system_prompt}]
        mem = memory or self.memory
        history = mem.get_messages_with_summary(messages, llm_call=self._summarize_call)
        llm_messages.extend(history)

        tool_schemas = None
        if tools:
            tool_schemas = [tool.to_openai_function() for tool in tools]

        # Check if history contains any tool calls (Anthropic requires tools= in this case)
        history_has_tool_calls = any(
            msg.get("tool_calls") or msg.get("role") == "tool" for msg in llm_messages
        )

        call_kwargs: dict[str, Any] = {
            "model": self.settings.model,
            "messages": llm_messages,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if self.settings.reasoning_effort:
            call_kwargs["reasoning_effort"] = self.settings.reasoning_effort
        if tool_schemas:
            call_kwargs["tools"] = tool_schemas
            call_kwargs["tool_choice"] = "auto"
        elif history_has_tool_calls and self.settings.model.startswith("claude"):
            # Anthropic requires tools= param if history contains tool calls
            # Pass empty tools list to satisfy the requirement
            call_kwargs["tools"] = []
        if self.settings.api_base:
            call_kwargs["api_base"] = self.settings.api_base
        if self.settings.api_key:
            call_kwargs["api_key"] = self.settings.api_key
        if self.settings.top_p != 1.0:
            call_kwargs["top_p"] = self.settings.top_p
        if self.settings.frequency_penalty != 0.0:
            call_kwargs["frequency_penalty"] = self.settings.frequency_penalty
        if self.settings.presence_penalty != 0.0:
            call_kwargs["presence_penalty"] = self.settings.presence_penalty

        def _extract_response(
            raw_response: Any,
        ) -> tuple[str | None, list[Any] | None, dict | None, str, str]:
            choices = (
                raw_response["choices"] if isinstance(raw_response, dict) else raw_response.choices
            )
            if not choices:
                raise ValueError(
                    "LLM returned empty choices array - check API status or rate limits"
                )
            choice = choices[0]
            message = choice["message"] if isinstance(choice, dict) else choice.message
            tool_calls = (
                message.get("tool_calls")
                if isinstance(message, dict)
                else getattr(message, "tool_calls", None)
            )
            content = message.get("content") if isinstance(message, dict) else message.content
            usage = (
                raw_response.get("usage") if isinstance(raw_response, dict) else raw_response.usage
            )
            usage_dict = None
            if usage:
                try:
                    usage_dict = dict(usage)
                except (TypeError, ValueError):
                    usage_dict = {
                        "prompt_tokens": getattr(usage, "prompt_tokens", 0),
                        "completion_tokens": getattr(usage, "completion_tokens", 0),
                        "total_tokens": getattr(usage, "total_tokens", 0),
                    }
            finish_reason = (
                choice.get("finish_reason") if isinstance(choice, dict) else choice.finish_reason
            )
            model = (
                raw_response.get("model") if isinstance(raw_response, dict) else raw_response.model
            )
            return (
                content,
                tool_calls,
                usage_dict,
                finish_reason or "",
                model or self.settings.model,
            )

        def _call_llm(kwargs: dict[str, Any]) -> Any:
            return self._retry_with_backoff(lambda: litellm.completion(**kwargs))

        try:
            response = _call_llm(call_kwargs)
        except Exception as exc:  # noqa: BLE001
            return LLMResponse(
                content=f"LLM Error: {exc}",
                tool_calls=None,
                usage=None,
                model=self.settings.model,
                finish_reason="error",
            )

        content, tool_calls, usage_dict, finish_reason, model = _extract_response(response)

        # Retry once if the model hit output length and produced no visible content.
        if not tool_calls and not content and finish_reason == "length":
            fallback_kwargs = dict(call_kwargs)
            fallback_kwargs["max_tokens"] = max(self.settings.max_tokens, 4096)
            if not self.settings.reasoning_effort:
                fallback_kwargs["reasoning_effort"] = "low"
            with suppress(Exception):
                response = _call_llm(fallback_kwargs)
                content, tool_calls, usage_dict, finish_reason, model = _extract_response(response)

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=usage_dict,
            model=model or self.settings.model,
            finish_reason=finish_reason or "",
        )

    def generate_structured(self, prompt: str, schema: type[T]) -> T:
        if litellm is None:
            raise RuntimeError("litellm is not installed in this environment")

        schema_json = schema.model_json_schema()
        schema_prompt = f"{prompt}\n\nSchema:\n{json.dumps(schema_json, indent=2)}"
        completion_args = {
            "model": self.settings.model,
            "messages": [
                {"role": "system", "content": "Return JSON that matches the provided schema."},
                {"role": "user", "content": schema_prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema.__name__,
                    "schema": schema_json,
                    "strict": True,
                },
            },
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if self.settings.api_base:
            completion_args["api_base"] = self.settings.api_base
        if self.settings.api_key:
            completion_args["api_key"] = self.settings.api_key
        try:
            response = litellm.completion(**completion_args)
        except Exception:  # noqa: BLE001
            completion_args["response_format"] = {"type": "json_object"}
            response = litellm.completion(**completion_args)
        content = response["choices"][0]["message"]["content"]
        data = content if isinstance(content, dict) else json.loads(content)
        return schema.model_validate(data)

    def _summarize_call(self, prompt: str) -> str:
        if litellm is None:
            raise RuntimeError("litellm is not installed in this environment")

        completion_args = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are a terse summarizer for an infrastructure assistant.",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 1000,
        }
        if self.settings.api_base:
            completion_args["api_base"] = self.settings.api_base
        if self.settings.api_key:
            completion_args["api_key"] = self.settings.api_key
        try:
            response = litellm.completion(**completion_args)
            message = (
                response["choices"][0]["message"]
                if isinstance(response, dict)
                else response.choices[0].message
            )
            if isinstance(message, dict):
                return message.get("content", "") or ""
            return message.content or ""
        except Exception as exc:  # noqa: BLE001
            return f"[Summarization failed: {exc}]"

    def clear_memory(self) -> None:
        """Clear conversation memory and summary cache."""
        self.memory.clear_summary_cache()

    def get_memory_stats(self) -> dict:
        """Get memory usage statistics."""
        return self.memory.get_stats()


@dataclass
class LLMResponse:
    """Response from LLM."""

    content: str | None
    tool_calls: list[Any] | None
    usage: dict | None
    model: str = ""
    finish_reason: str = ""
