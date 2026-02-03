import React, { useState } from "react";
import type { SandboxPermissions } from "../api";

type PolicyListProps = {
  showHeader?: boolean;
  permissions: SandboxPermissions | null;
  isLoading: boolean;
  onUpdate: (permissions: SandboxPermissions) => Promise<void>;
};

export function PolicyList({ 
  showHeader = true, 
  permissions,
  isLoading,
  onUpdate 
}: PolicyListProps) {
  const [isSaving, setIsSaving] = useState(false);

  const handleToggle = async (key: keyof SandboxPermissions) => {
    if (!permissions || isSaving) return;
    const newPermissions = { ...permissions, [key]: !permissions[key] };
    
    try {
      setIsSaving(true);
      await onUpdate(newPermissions);
    } catch (err) {
      console.error("Failed to save permissions:", err);
    } finally {
      setIsSaving(false);
    }
  };

  const permissionItems = [
    {
      key: "allow_shell" as keyof SandboxPermissions,
      label: "Allow Shell Commands",
      description: "Enable terminal tool execution",
    },
    {
      key: "allow_network" as keyof SandboxPermissions,
      label: "Allow Network Access",
      description: "Enable browser tool and HTTP requests",
    },
    {
      key: "allow_file_write" as keyof SandboxPermissions,
      label: "Allow File Write",
      description: "Enable file_edit tool write operations",
    },
    {
      key: "allow_unsafe_tools" as keyof SandboxPermissions,
      label: "Allow System Tools",
      description: "Enable internal tools (graph queries, planning, reasoning)",
    },
  ];

  return (
    <div className="permissions-list">
      {showHeader && <div className="section-title">Sandbox Runtime Permissions</div>}
      {isLoading && <div className="text-muted">Loading permissions...</div>}
      {!isLoading && permissions && (
        <>
          <div className="settings-list">
            {permissionItems.map((item) => (
              <div key={item.key} className="setting-row">
                <div className="setting-info">
                  <div className="setting-label">{item.label}</div>
                  <div className="setting-desc">{item.description}</div>
                </div>
                <label className="toggle-switch">
                  <input
                    type="checkbox"
                    checked={permissions[item.key] as boolean}
                    onChange={() => handleToggle(item.key)}
                    disabled={isSaving}
                  />
                  <span className="toggle-slider" />
                </label>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
