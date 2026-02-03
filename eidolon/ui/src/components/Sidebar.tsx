import React from "react";
import {
  Kanban,
  MessageSquare,
  Wifi,
  GitBranch,
  FileText,
  Settings,
  ChevronLeft,
  Trash,
} from "lucide-react";
import type { ChatSessionSummary } from "../api";

const navItems = [
  { id: "networks", name: "Networks", icon: Wifi },
  { id: "graph", name: "Graph", icon: GitBranch },
  { id: "audit", name: "Audit", icon: FileText },
  { id: "settings", name: "Settings", icon: Settings },
];

interface SidebarProps {
  isCollapsed: boolean;
  onToggle: () => void;
  activeTab?: string;
  onTabChange?: (tabId: string) => void;
  sessions: ChatSessionSummary[];
  activeSessionId: string | null;
  onNewChat: () => void;
  onSelectSession: (sessionId: string) => void;
  onDeleteSession: (sessionId: string) => void;
}

export function Sidebar({
  isCollapsed,
  onToggle,
  activeTab = "chat",
  onTabChange,
  sessions,
  activeSessionId,
  onNewChat,
  onSelectSession,
  onDeleteSession,
}: SidebarProps) {
  const handleClick = (tabId: string) => {
    if (onTabChange) {
      onTabChange(tabId);
    }
  };

  const handleCreateClick = () => {
    onNewChat();
  };

  const handleSessionSelect = (sessionId: string) => {
    onSelectSession(sessionId);
  };

  const truncateTitle = (value: string, maxLength = 40) => {
    const normalized = value.replace(/\s+/g, " ").trim();
    if (!normalized) {
      return "Untitled chat";
    }
    if (normalized.length <= maxLength) {
      return normalized;
    }
    return `${normalized.slice(0, maxLength).trim()}...`;
  };

  const formatSessionTitle = (session: ChatSessionSummary) => {
    const title = session.title?.trim();
    if (title) {
      return truncateTitle(title);
    }
    const createdAt = new Date(session.created_at);
    if (Number.isNaN(createdAt.getTime())) {
      return "Untitled chat";
    }
    const date = createdAt.toLocaleDateString();
    const time = createdAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return `Chat ${date} ${time}`;
  };

  return (
    <aside className={`sidebar ${isCollapsed ? "collapsed" : ""}`}>
      <div className="sidebar-header">
        <div 
          className={`brand ${isCollapsed ? "clickable" : ""}`}
          onClick={isCollapsed ? onToggle : undefined}
          title={isCollapsed ? "Expand" : ""}
        >
          <Kanban size={24} style={{ transform: "rotate(270deg)" }} />
          {!isCollapsed && <span>Eidolon</span>}
        </div>
        {!isCollapsed && (
          <button className="icon-btn" onClick={onToggle} title="Collapse">
            <ChevronLeft size={20} />
          </button>
        )}
      </div>
      
      <div className="sidebar-scroll">
        <nav>
          {navItems.map((item) => (
            <button 
              key={item.id} 
              className={`nav-item ${activeTab === item.id ? "active" : ""}`}
              onClick={() => handleClick(item.id)}
              title={isCollapsed ? item.name : ""}
            >
              <item.icon size={16} />
              {!isCollapsed && item.name}
            </button>
          ))}
          <button
            className={`nav-item ${activeTab === "chat" && !activeSessionId ? "active" : ""}`}
            onClick={handleCreateClick}
            title={isCollapsed ? "New Chat" : ""}
          >
            <MessageSquare size={16} />
            {!isCollapsed && "New Chat"}
          </button>
        </nav>
        {!isCollapsed && (
          <div className="sessions-header">Your Chats</div>
        )}
        <div className="sessions-list">
          {sessions.length === 0 ? (
            <div className="sessions-empty">No chats yet</div>
          ) : (
            sessions.map((session) => {
              const label = formatSessionTitle(session);
              const isActive = activeTab === "chat" && activeSessionId === session.session_id;
              return (
                <div
                  key={session.session_id}
                  className={`session-item ${isActive ? "active" : ""}`}
                >
                  <button
                    className="session-select"
                    onClick={() => handleSessionSelect(session.session_id)}
                    title={label}
                  >
                    {!isCollapsed && <span className="session-title">{label}</span>}
                  </button>
                  {!isCollapsed && (
                    <button
                      className="session-delete"
                      onClick={(event) => {
                        event.stopPropagation();
                        onDeleteSession(session.session_id);
                      }}
                      title="Delete chat"
                    >
                      <Trash size={14} />
                    </button>
                  )}
                </div>
              );
            })
          )}
        </div>
      </div>
    </aside>
  );
}
