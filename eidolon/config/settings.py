from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Neo4jSettings(BaseModel):
    uri: str = Field(default="bolt://localhost:7687", description="Neo4j Bolt URI")
    user: str = Field(default="neo4j", description="Neo4j user")
    password: str = Field(default="password", description="Neo4j password")
    database: str = Field(default="neo4j", description="Neo4j database name")


class PostgresSettings(BaseModel):
    url: str = Field(
        default="postgresql://postgres:password@localhost:5432/eidolon",
        description="Postgres connection string for audit/session data",
    )


class LLMSettings(BaseModel):
    model: str = Field(default="gpt-5-mini", description="Default LiteLLM model name")
    api_base: str | None = Field(default=None, description="Optional LiteLLM proxy base URL")
    api_key: str | None = Field(default=None, description="API key used by LiteLLM")
    temperature: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Default generation temperature"
    )
    max_tokens: int = Field(default=1024, ge=128, description="Token cap for responses")
    reasoning_effort: Literal["low", "medium", "high"] | None = Field(
        default=None,
        description="Optional reasoning effort hint for supported models",
    )
    top_p: float = Field(default=1.0, ge=0.0, le=1.0, description="Nucleus sampling")
    frequency_penalty: float = Field(default=0.0, ge=-2.0, le=2.0, description="Frequency penalty")
    presence_penalty: float = Field(default=0.0, ge=-2.0, le=2.0, description="Presence penalty")
    max_context_tokens: int = Field(default=128000, ge=1024, description="Max context window")
    max_retries: int = Field(default=5, ge=0, description="Retry attempts for rate limits")
    retry_delay: float = Field(default=2.0, ge=0.1, description="Base retry delay in seconds")

    @field_validator("reasoning_effort", mode="before")
    @classmethod
    def normalize_reasoning_effort(cls, v):
        if v is None:
            return None
        if isinstance(v, str):
            cleaned = v.strip().lower()
            return cleaned or None
        return v


class APISettings(BaseModel):
    host: str = Field(default="0.0.0.0", description="API bind host")  # noqa: S104
    port: int = Field(default=8080, ge=1, le=65535, description="API bind port")
    cors_origins: list[str] = Field(
        default_factory=lambda: ["*"], description="Allowed CORS origins"
    )


class AuthSettings(BaseModel):
    mode: Literal["header", "jwt", "none"] = Field(
        default="header",
        description="Auth mode: header (dev), jwt (HS256), or none (no auth checks).",
    )
    jwt_secret: str | None = Field(
        default=None,
        description="Shared secret for HS256 JWT verification when auth.mode=jwt.",
    )
    jwt_issuer: str | None = Field(default=None, description="Expected JWT issuer (iss claim).")
    jwt_audience: str | None = Field(default=None, description="Expected JWT audience (aud claim).")
    header_user_id: str = Field(default="x-user-id", description="Header for user identity.")
    header_roles: str = Field(default="x-roles", description="Header for roles list.")


class SandboxPermissions(BaseModel):
    allow_unsafe_tools: bool = Field(
        default=True,
        description="Allow system tools (graph queries, planning, reasoning tools).",
    )
    allow_shell: bool = Field(default=True, description="Allow terminal tool usage.")
    allow_network: bool = Field(default=True, description="Allow browser tool usage.")
    allow_file_write: bool = Field(default=False, description="Allow file_edit write operations.")
    allowed_tools: list[str] | None = Field(
        default=None,
        description="Optional allowlist of tool names; when set, only these are permitted.",
    )
    blocked_tools: list[str] = Field(
        default_factory=list,
        description="Optional blocklist of tool names to deny.",
    )

    @field_validator("allowed_tools", "blocked_tools", mode="before")
    @classmethod
    def parse_list_from_env(cls, v, info):
        """Handle empty strings from environment variables for list fields."""
        if v == "":
            return None if info.field_name == "allowed_tools" else []
        return v


class Settings(BaseSettings):
    environment: str = Field(default="local", description="Runtime environment label")
    log_level: str = Field(default="INFO", description="Structured log level")
    neo4j: Neo4jSettings = Field(default_factory=Neo4jSettings)
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    api: APISettings = Field(default_factory=APISettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    sandbox: SandboxPermissions = Field(default_factory=SandboxPermissions)

    model_config = SettingsConfigDict(
        env_prefix="EIDOLON_",
        env_file=".env",
        env_nested_delimiter="__",
        extra="ignore",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings instance to avoid repeated env parsing."""
    return Settings()
