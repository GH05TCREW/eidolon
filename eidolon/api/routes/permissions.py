from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from eidolon.api.dependencies import get_settings_store, require_roles
from eidolon.api.middleware.auth import IdentityContext
from eidolon.config.settings import SandboxPermissions
from eidolon.core.stores import SettingsStore

router = APIRouter(prefix="/permissions", tags=["permissions"])
_SETTINGS_STORE = Depends(get_settings_store)
_VIEWER_IDENTITY = Depends(require_roles("viewer", "planner", "executor"))
_EXECUTOR_IDENTITY = Depends(require_roles("executor"))


class PermissionsResponse(BaseModel):
    sandbox: SandboxPermissions


@router.get("/", response_model=PermissionsResponse)
def get_permissions(
    identity: IdentityContext = _VIEWER_IDENTITY,
    store: SettingsStore = _SETTINGS_STORE,
) -> PermissionsResponse:
    """Get sandbox permissions."""
    return PermissionsResponse(sandbox=store.get_settings())


@router.put("/", response_model=PermissionsResponse)
def update_permissions(
    permissions: SandboxPermissions,
    identity: IdentityContext = _EXECUTOR_IDENTITY,
    store: SettingsStore = _SETTINGS_STORE,
) -> PermissionsResponse:
    """Update sandbox permissions."""
    store.update_settings(permissions)
    return PermissionsResponse(sandbox=store.get_settings())
