-- Postgres schema for audit trail, chat sessions, approvals, and rate limits.

CREATE TABLE IF NOT EXISTS audit_events (
    id UUID PRIMARY KEY,
    event_type TEXT NOT NULL,
    details JSONB NOT NULL,
    status TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_sessions (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id UUID PRIMARY KEY,
    session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS approvals (
    id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    token TEXT NOT NULL,
    action TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_approvals_token ON approvals (token);
CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit_events (event_type);
CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages (session_id);

CREATE TABLE IF NOT EXISTS sandbox_permissions (
    id TEXT PRIMARY KEY DEFAULT 'default',
    permissions JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS app_settings (
    id TEXT PRIMARY KEY DEFAULT 'default',
    settings JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS scan_configs (
    id SERIAL PRIMARY KEY,
    user_id TEXT NOT NULL UNIQUE,
    network_cidrs TEXT[] NOT NULL,
    ports INTEGER[] NOT NULL,
    port_preset TEXT NOT NULL,
    collectors JSONB NOT NULL,
    options JSONB NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Removed scan_runs table - using audit_log for scan history instead
