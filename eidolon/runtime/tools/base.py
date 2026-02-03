from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """Base class for agent tools."""

    name: str = "tool"
    description: str = ""
    sandbox_execution: bool = True

    @property
    def parameters_schema(self) -> dict[str, Any]:
        """JSON Schema for tool parameters. Override in subclasses for specific schemas."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    def to_openai_function(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters_schema,
            },
        }

    @abstractmethod
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool with a typed payload."""
