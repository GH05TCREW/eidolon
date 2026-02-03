from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from eidolon.config.settings import LLMSettings, get_settings


class ThemeSettings(BaseModel):
    mode: Literal["dark", "light"] = Field(default="dark")


class AppSettings(BaseModel):
    theme: ThemeSettings = Field(default_factory=ThemeSettings)
    llm: LLMSettings = Field(default_factory=lambda: get_settings().llm)
