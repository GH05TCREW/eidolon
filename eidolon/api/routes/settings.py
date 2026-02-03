from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from eidolon.api.dependencies import get_llm_client, get_settings_store, require_roles
from eidolon.api.middleware.auth import IdentityContext
from eidolon.config.settings import LLMSettings, get_settings
from eidolon.core.models.settings import AppSettings, ThemeSettings
from eidolon.core.stores import SettingsStore

router = APIRouter(prefix="/settings", tags=["settings"])
_SETTINGS_STORE = Depends(get_settings_store)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))


class LLMSettingsUpdate(BaseModel):
    model: str | None = None
    api_base: str | None = None
    api_key: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(default=None, ge=128)


class AppSettingsUpdate(BaseModel):
    theme: ThemeSettings | None = None
    llm: LLMSettingsUpdate | None = None


class AppSettingsResponse(BaseModel):
    theme: ThemeSettings
    llm: LLMSettings


@router.get("/", response_model=AppSettingsResponse)
def get_app_settings(
    store: SettingsStore = _SETTINGS_STORE,
    identity: IdentityContext = _VIEWER_IDENTITY,
) -> AppSettingsResponse:
    settings = store.get_app_settings()
    return AppSettingsResponse(theme=settings.theme, llm=settings.llm)


@router.put("/", response_model=AppSettingsResponse)
def update_app_settings(
    payload: AppSettingsUpdate,
    store: SettingsStore = _SETTINGS_STORE,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
) -> AppSettingsResponse:
    current = store.get_app_settings()
    theme = payload.theme or current.theme
    llm = current.llm

    if payload.llm:
        defaults = get_settings().llm.model_dump()
        data = llm.model_dump()
        for key, value in payload.llm.model_dump(exclude_unset=True).items():
            if isinstance(value, str):
                value = value.strip()
            if value is None or value == "":
                data[key] = defaults.get(key)
            else:
                data[key] = value
        llm = LLMSettings(**data)

    updated = AppSettings(theme=theme, llm=llm)
    store.update_app_settings(updated)
    get_llm_client.cache_clear()
    return AppSettingsResponse(theme=updated.theme, llm=updated.llm)
