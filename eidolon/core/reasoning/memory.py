"""Conversation memory management with summarization support."""

from collections.abc import Callable

SUMMARY_PROMPT = """Summarize the following conversation segment for an infrastructure assistant.
The summary will be used to continue the task, so preserve operational details and decisions.

What to preserve:
- Targets, systems, and environment details
- Tools executed and their outcomes
- Findings, errors, and important observations
- Decisions made and next steps
- Paths, commands, parameters, and identifiers

Compression approach:
- Consolidate repetition
- Keep technical precision
- Remove conversational back-and-forth

Conversation segment:
{conversation}

Provide a concise technical summary:"""


class ConversationMemory:
    """Manages conversation history with token limits and summarization."""

    def __init__(
        self,
        max_tokens: int = 128000,
        reserve_ratio: float = 0.8,
        recent_to_keep: int = 10,
        summarize_threshold: float = 0.6,
    ):
        self.max_tokens = max_tokens
        self.reserve_ratio = reserve_ratio
        self.recent_to_keep = recent_to_keep
        self.summarize_threshold = summarize_threshold
        self._encoder = None
        self._cached_summary: str | None = None
        self._summarized_count: int = 0

    @property
    def encoder(self):
        """Lazy load the tokenizer."""
        if self._encoder is None:
            try:
                import tiktoken

                self._encoder = tiktoken.get_encoding("cl100k_base")
            except ImportError:
                self._encoder = None
        return self._encoder

    def _count_tokens_with_litellm(self, text: str, model: str) -> int | None:
        """Try to count tokens using litellm for better accuracy."""
        try:
            import litellm
        except ImportError:
            return None

        try:
            count = litellm.token_counter(model=model, text=text)
            return int(count)
        except (RuntimeError, TypeError, ValueError):
            return None

    @property
    def token_budget(self) -> int:
        """Available tokens for history."""
        return int(self.max_tokens * self.reserve_ratio)

    def get_messages(self, messages: list[dict]) -> list[dict]:
        """
        Get messages that fit within token limit (sync, no summarization).
        Falls back to truncation if over budget.
        """
        if not messages:
            return []

        if self._cached_summary and len(messages) > self._summarized_count:
            summary_msg = {
                "role": "system",
                "content": f"Previous conversation summary:\n{self._cached_summary}",
            }
            recent = messages[self._summarized_count :]
            return [
                summary_msg,
                *self._truncate_to_fit(recent, self.token_budget - self._count_tokens(summary_msg)),
            ]

        return self._truncate_to_fit(messages, self.token_budget)

    def get_messages_with_summary(
        self, messages: list[dict], llm_call: Callable[[str], str]
    ) -> list[dict]:
        """
        Get messages, summarizing older ones if needed.
        """
        if not messages:
            return []

        total_tokens = self.get_total_tokens(messages)
        threshold_tokens = int(self.token_budget * self.summarize_threshold)

        if total_tokens <= threshold_tokens:
            return messages

        if len(messages) <= self.recent_to_keep:
            return self._truncate_to_fit(messages, self.token_budget)

        split_point = len(messages) - self.recent_to_keep
        older = messages[:split_point]
        recent = messages[-self.recent_to_keep :]

        if split_point <= self._summarized_count and self._cached_summary:
            result = [
                {
                    "role": "system",
                    "content": f"Previous conversation summary:\n{self._cached_summary}",
                }
            ]
            result.extend(recent)
            return result

        summary = self._summarize(older, llm_call)

        self._cached_summary = summary
        self._summarized_count = split_point

        result = [{"role": "system", "content": f"Previous conversation summary:\n{summary}"}]
        result.extend(recent)
        return result

    def _summarize(self, messages: list[dict], llm_call: Callable[[str], str]) -> str:
        """Summarize a list of messages using chunked approach."""
        if not messages:
            return "[No messages to summarize]"

        chunk_size = 10
        summaries = []

        for i in range(0, len(messages), chunk_size):
            chunk = messages[i : i + chunk_size]
            conversation_text = self._format_for_summary(chunk)
            prompt = SUMMARY_PROMPT.format(conversation=conversation_text)

            try:
                chunk_summary = llm_call(prompt)
                if chunk_summary and chunk_summary.strip():
                    summaries.append(chunk_summary.strip())
            except Exception as exc:  # noqa: BLE001
                summaries.append(
                    f"[{len(chunk)} messages from segment {i // chunk_size + 1} - "
                    f"summary failed: {exc}]"
                )

        if not summaries:
            return f"[{len(messages)} earlier messages - all summarization attempts failed]"

        if len(summaries) == 1:
            return summaries[0]

        combined = "\n\n".join(f"Segment {i + 1}: {summary}" for i, summary in enumerate(summaries))
        return combined

    def _format_for_summary(self, messages: list[dict]) -> str:
        """Format messages as text for summarization."""
        lines = []
        for msg in messages:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if not isinstance(content, str):
                content = str(content)

            max_length = 4000 if role == "tool" else 2000
            if len(content) > max_length:
                if role == "tool":
                    half = max_length // 2
                    content = (
                        content[:half]
                        + f"\n...[{len(content) - max_length} chars truncated]...\n"
                        + content[-half:]
                    )
                else:
                    content = content[:max_length] + "...[truncated]"

            if role == "user":
                lines.append(f"User: {content}")
            elif role == "assistant":
                lines.append(f"Assistant: {content}")
            elif role == "tool":
                tool_name = msg.get("name", "tool")
                lines.append(f"Tool ({tool_name}): {content}")
            elif role == "system":
                continue

        return "\n\n".join(lines)

    def _truncate_to_fit(self, messages: list[dict], budget: int) -> list[dict]:
        """Truncate messages from the beginning to fit budget."""
        total_tokens = 0
        result = []

        for msg in reversed(messages):
            msg_tokens = self._count_tokens(msg)
            if total_tokens + msg_tokens > budget:
                break
            result.insert(0, msg)
            total_tokens += msg_tokens

        return result

    def _count_tokens(self, message: dict) -> int:
        """Count tokens in a message."""
        content = message.get("content", "")

        if isinstance(content, str):
            if self.encoder:
                return len(self.encoder.encode(content))
            return int(len(content.split()) * 1.3)

        return 0

    def get_total_tokens(self, messages: list[dict]) -> int:
        """Get total token count for messages."""
        return sum(self._count_tokens(msg) for msg in messages)

    def fits_in_context(self, messages: list[dict]) -> bool:
        """Check if messages fit in context window."""
        return self.get_total_tokens(messages) <= self.token_budget

    def clear_summary_cache(self):
        """Clear the cached summary."""
        self._cached_summary = None
        self._summarized_count = 0

    def get_stats(self) -> dict:
        """Get memory statistics."""
        return {
            "max_tokens": self.max_tokens,
            "token_budget": self.token_budget,
            "summarize_threshold": int(self.token_budget * self.summarize_threshold),
            "recent_to_keep": self.recent_to_keep,
            "has_summary": self._cached_summary is not None,
            "summarized_message_count": self._summarized_count,
        }
