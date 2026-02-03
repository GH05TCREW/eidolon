import React, { useEffect, useMemo, useState } from "react";
import {
  Cpu,
  Database,
  Download,
  Palette,
  Save,
  Shield,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import type { AppSettings, AppSettingsUpdate, SandboxPermissions } from "../api";
import { getSandboxPermissions, updateSandboxPermissions } from "../api";
import { PolicyList } from "./PolicyList";

type SettingsPanelProps = {
  settings: AppSettings | null;
  isLoading: boolean;
  onSave: (payload: AppSettingsUpdate) => Promise<void>;
  actions: SettingsActions;
  busy: SettingsBusy;
};

type SettingsActions = {
  wipeChats: () => Promise<void>;
  clearAudit: () => Promise<void>;
  resetGraph: () => Promise<void>;
  exportChats: () => Promise<void>;
  exportGraph: () => Promise<void>;
};

type SettingsBusy = {
  wipeChats: boolean;
  clearAudit: boolean;
  resetGraph: boolean;
  exportChats: boolean;
  exportGraph: boolean;
};

type SectionId =
  | "appearance"
  | "llm"
  | "security"
  | "data"
  | "export";

const settingsSections: { id: SectionId; label: string; icon: LucideIcon }[] = [
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "llm", label: "LiteLLM", icon: Cpu },
  { id: "security", label: "Security", icon: Shield },
  { id: "data", label: "Data", icon: Database },
  { id: "export", label: "Export", icon: Download },
];

type LlmDraft = {
  model: string;
  api_base: string;
  api_key: string;
  temperature: string;
  max_tokens: string;
};

const defaultDraft: LlmDraft = {
  model: "",
  api_base: "",
  api_key: "",
  temperature: "",
  max_tokens: "",
};

export function SettingsPanel({
  settings,
  isLoading,
  onSave,
  actions,
  busy,
}: SettingsPanelProps) {
  const [activeSection, setActiveSection] = useState<SectionId>("appearance");
  const [themeMode, setThemeMode] = useState<"dark" | "light">("dark");
  const [llmDraft, setLlmDraft] = useState<LlmDraft>(defaultDraft);
  const [isSavingTheme, setIsSavingTheme] = useState(false);
  const [isSavingLlm, setIsSavingLlm] = useState(false);
  const [permissions, setPermissions] = useState<SandboxPermissions | null>(null);
  const [isLoadingPermissions, setIsLoadingPermissions] = useState(true);

  useEffect(() => {
    if (!settings) {
      return;
    }
    setThemeMode(settings.theme.mode);
    setLlmDraft({
      model: settings.llm.model ?? "",
      api_base: settings.llm.api_base ?? "",
      api_key: settings.llm.api_key ?? "",
      temperature: Number.isFinite(settings.llm.temperature)
        ? String(settings.llm.temperature)
        : "",
      max_tokens: Number.isFinite(settings.llm.max_tokens)
        ? String(settings.llm.max_tokens)
        : "",
    });
  }, [settings]);

  useEffect(() => {
    const loadPermissions = async () => {
      try {
        setIsLoadingPermissions(true);
        const data = await getSandboxPermissions();
        setPermissions(data);
      } catch (err) {
        console.error("Failed to load permissions:", err);
      } finally {
        setIsLoadingPermissions(false);
      }
    };
    loadPermissions();
  }, []);

  const handlePermissionsUpdate = async (newPermissions: SandboxPermissions) => {
    setPermissions(newPermissions);
    try {
      await updateSandboxPermissions(newPermissions);
    } catch (err) {
      console.error("Failed to save permissions:", err);
      // Revert on error - reload from server
      const data = await getSandboxPermissions();
      setPermissions(data);
      throw err;
    }
  };

  const themeDirty = settings ? themeMode !== settings.theme.mode : false;

  const llmDirty = useMemo(() => {
    if (!settings) {
      return false;
    }
    return (
      llmDraft.model !== (settings.llm.model ?? "") ||
      llmDraft.api_base !== (settings.llm.api_base ?? "") ||
      llmDraft.api_key !== (settings.llm.api_key ?? "") ||
      llmDraft.temperature !== String(settings.llm.temperature ?? "") ||
      llmDraft.max_tokens !== String(settings.llm.max_tokens ?? "")
    );
  }, [llmDraft, settings]);

  const handleThemeSave = async () => {
    setIsSavingTheme(true);
    try {
      await onSave({ theme: { mode: themeMode } });
    } finally {
      setIsSavingTheme(false);
    }
  };

  const handleLlmSave = async () => {
    setIsSavingLlm(true);
    const temperature = Number.parseFloat(llmDraft.temperature);
    const maxTokens = Number.parseInt(llmDraft.max_tokens, 10);
    const payload: AppSettingsUpdate = {
      llm: {
        model: llmDraft.model.trim() || null,
        api_base: llmDraft.api_base.trim() || null,
        api_key: llmDraft.api_key.trim() || null,
        temperature: Number.isFinite(temperature) ? temperature : null,
        max_tokens: Number.isFinite(maxTokens) ? maxTokens : null,
      },
    };
    try {
      await onSave(payload);
    } finally {
      setIsSavingLlm(false);
    }
  };

  return (
    <div className="settings-page">
      <div className="settings-menu">
        {settingsSections.map((section) => (
          <button
            key={section.id}
            className={`settings-menu-item ${activeSection === section.id ? "active" : ""}`}
            onClick={() => setActiveSection(section.id)}
          >
            <section.icon size={16} />
            <span>{section.label}</span>
          </button>
        ))}
      </div>

      <div className="settings-content">
        {activeSection === "appearance" && (
          <section className="settings-card">
            <div>
              <div className="settings-card-title">Theme</div>
              <div className="settings-card-subtitle">
                Switch between light and dark modes across the UI.
              </div>
            </div>
            <div className="settings-toggle">
              <button
                className={`settings-toggle-btn ${themeMode === "dark" ? "active" : ""}`}
                onClick={() => setThemeMode("dark")}
                disabled={isLoading}
              >
                Dark
              </button>
              <button
                className={`settings-toggle-btn ${themeMode === "light" ? "active" : ""}`}
                onClick={() => setThemeMode("light")}
                disabled={isLoading}
              >
                Light
              </button>
            </div>
            <div className="settings-actions">
              <button
                className="settings-save-btn"
                onClick={handleThemeSave}
                disabled={isLoading || isSavingTheme || !themeDirty}
              >
                <Save size={16} />
                Save theme
              </button>
            </div>
          </section>
        )}

        {activeSection === "llm" && (
          <section className="settings-card">
            <div>
              <div className="settings-card-title">LiteLLM Configuration</div>
              <div className="settings-card-subtitle">
                Provide model and credentials.
              </div>
            </div>
            <div className="settings-field">
              <label className="settings-label" htmlFor="llm-model">
                Model
              </label>
              <input
                id="llm-model"
                className="settings-input"
                value={llmDraft.model}
                onChange={(event) => setLlmDraft((prev) => ({ ...prev, model: event.target.value }))}
                placeholder="gpt-5-mini"
                disabled={isLoading}
              />
            </div>
            <div className="settings-field">
              <label className="settings-label" htmlFor="llm-api-base">
                API Base URL
              </label>
              <input
                id="llm-api-base"
                className="settings-input"
                value={llmDraft.api_base}
                onChange={(event) => setLlmDraft((prev) => ({ ...prev, api_base: event.target.value }))}
                placeholder="https://api.openai.com/v1"
                disabled={isLoading}
              />
            </div>
            <div className="settings-field">
              <label className="settings-label" htmlFor="llm-api-key">
                API Key
              </label>
              <input
                id="llm-api-key"
                className="settings-input"
                type="password"
                value={llmDraft.api_key}
                onChange={(event) => setLlmDraft((prev) => ({ ...prev, api_key: event.target.value }))}
                placeholder="sk-..."
                disabled={isLoading}
              />
              <div className="settings-hint">
                Stored in the database and used by the backend for chat responses.
              </div>
            </div>
            <div className="settings-row">
              <div className="settings-field">
                <label className="settings-label" htmlFor="llm-temperature">
                  Temperature
                </label>
                <input
                  id="llm-temperature"
                  className="settings-input"
                  type="number"
                  step="0.1"
                  min="0"
                  max="1"
                  value={llmDraft.temperature}
                  onChange={(event) =>
                    setLlmDraft((prev) => ({ ...prev, temperature: event.target.value }))
                  }
                  disabled={isLoading}
                />
              </div>
              <div className="settings-field">
                <label className="settings-label" htmlFor="llm-max-tokens">
                  Max Tokens
                </label>
                <input
                  id="llm-max-tokens"
                  className="settings-input"
                  type="number"
                  min="128"
                  value={llmDraft.max_tokens}
                  onChange={(event) =>
                    setLlmDraft((prev) => ({ ...prev, max_tokens: event.target.value }))
                  }
                  disabled={isLoading}
                />
              </div>
            </div>
            <div className="settings-actions">
              <button
                className="settings-save-btn"
                onClick={handleLlmSave}
                disabled={isLoading || isSavingLlm || !llmDirty}
              >
                <Save size={16} />
                Save LiteLLM settings
              </button>
            </div>
          </section>
        )}

        {activeSection === "security" && (
          <section className="settings-card">
            <div>
              <div className="settings-card-title">Sandbox Permissions</div>
              <div className="settings-card-subtitle">
                Control which tools and capabilities are enabled for runtime agents.
              </div>
            </div>
            <div className="settings-embedded">
              <PolicyList 
                showHeader={false} 
                permissions={permissions}
                isLoading={isLoadingPermissions}
                onUpdate={handlePermissionsUpdate}
              />
            </div>
          </section>
        )}

        {activeSection === "data" && (
          <section className="settings-card">
            <div>
              <div className="settings-card-title">Data Management</div>
              <div className="settings-card-subtitle">
                Permanently remove stored data from this workspace.
              </div>
            </div>
            <div className="settings-action-list">
              <div className="settings-action">
                <div className="settings-action-meta">
                  <div className="settings-action-title">Wipe all chats</div>
                  <div className="settings-action-desc">
                    Deletes every chat session and message for this user.
                  </div>
                </div>
                <button
                  className="settings-action-btn danger"
                  onClick={actions.wipeChats}
                  disabled={isLoading || busy.wipeChats}
                >
                  <Trash2 size={14} />
                  Delete chats
                </button>
              </div>
              <div className="settings-action">
                <div className="settings-action-meta">
                  <div className="settings-action-title">Clear audit logs</div>
                  <div className="settings-action-desc">
                    Removes event logs and audit history entries.
                  </div>
                </div>
                <button
                  className="settings-action-btn danger"
                  onClick={actions.clearAudit}
                  disabled={isLoading || busy.clearAudit}
                >
                  <Trash2 size={14} />
                  Clear logs
                </button>
              </div>
              <div className="settings-action">
                <div className="settings-action-meta">
                  <div className="settings-action-title">Reset graph data</div>
                  <div className="settings-action-desc">
                    Deletes networks, assets, and graph relationships.
                  </div>
                </div>
                <button
                  className="settings-action-btn danger"
                  onClick={actions.resetGraph}
                  disabled={isLoading || busy.resetGraph}
                >
                  <Trash2 size={14} />
                  Reset graph
                </button>
              </div>
            </div>
            <div className="settings-hint">These actions are irreversible.</div>
          </section>
        )}

        {activeSection === "export" && (
          <section className="settings-card">
            <div>
              <div className="settings-card-title">Export Data</div>
              <div className="settings-card-subtitle">
                Backup chats or export graph data for offline analysis.
              </div>
            </div>
            <div className="settings-action-list">
              <div className="settings-action">
                <div className="settings-action-meta">
                  <div className="settings-action-title">Export chats</div>
                  <div className="settings-action-desc">
                    Download all chat sessions as a JSON archive.
                  </div>
                </div>
                <button
                  className="settings-action-btn"
                  onClick={actions.exportChats}
                  disabled={isLoading || busy.exportChats}
                >
                  <Download size={14} />
                  Export chats
                </button>
              </div>
              <div className="settings-action">
                <div className="settings-action-meta">
                  <div className="settings-action-title">Export graph</div>
                  <div className="settings-action-desc">
                    Export networks and assets for external analysis.
                  </div>
                </div>
                <button
                  className="settings-action-btn"
                  onClick={actions.exportGraph}
                  disabled={isLoading || busy.exportGraph}
                >
                  <Download size={14} />
                  Export graph
                </button>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}

