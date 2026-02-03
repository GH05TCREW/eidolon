import React, { useCallback, useEffect, useMemo, useState } from "react";
import { Sidebar } from "./components/Sidebar";
import { StatsRow } from "./components/StatsRow";
import { NetworkMap } from "./components/NetworkMap";
import { DeviceList } from "./components/DeviceList";
import { NetworkList } from "./components/NetworkList";
import { EventLog } from "./components/EventLog";
import { ScannerControl } from "./components/ScannerControl";
import { ChatInterface } from "./components/ChatInterface";
import { RightPanel } from "./components/RightPanel";
import { ToastContainer, useToast } from "./components/Toast";
import { SettingsPanel } from "./components/SettingsPanel";
import { GraphView } from "./components/GraphView";
import {
  clearAuditEvents,
  createChatSession,
  deleteAllChatSessions,
  deleteChatSession,
  getAppSettings,
  getChatSession,
  getNodeId,
  listAssets,
  listAuditEvents,
  listChatSessions,
  listNetworks,
  resetGraph,
  updateAppSettings,
  type AppSettings,
  type AppSettingsUpdate,
  type AuditEvent,
  type ChatSession,
  type ChatSessionSummary,
  type GraphNode,
} from "./api";

const normalizeTitle = (value: string) => value.replace(/\s+/g, " ").trim();

const buildSessionTitle = (value: string, maxLength = 56) => {
  const normalized = normalizeTitle(value);
  if (!normalized) {
    return "New chat";
  }
  if (normalized.length <= maxLength) {
    return normalized;
  }
  return `${normalized.slice(0, maxLength).trim()}...`;
};

const toSessionSummary = (session: ChatSession): ChatSessionSummary => ({
  session_id: session.session_id,
  title: session.title ?? null,
  created_at: session.created_at,
  updated_at: session.updated_at,
  message_count: session.messages.length,
});

const buildExportFilename = (prefix: string) => {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `${prefix}-${stamp}.json`;
};

const downloadJson = (filename: string, payload: unknown) => {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
};

export default function App() {
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false);
  const [isRightPanelCollapsed, setIsRightPanelCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState("chat");
  const [appSettings, setAppSettings] = useState<AppSettings | null>(null);
  const [isAppSettingsLoading, setIsAppSettingsLoading] = useState(true);
  const [sessions, setSessions] = useState<ChatSessionSummary[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [assets, setAssets] = useState<GraphNode[]>([]);
  const [networks, setNetworks] = useState<GraphNode[]>([]);
  const [auditEvents, setAuditEvents] = useState<AuditEvent[]>([]);
  const [auditTotal, setAuditTotal] = useState(0);
  const [selectedNetworkId, setSelectedNetworkId] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isWipingChats, setIsWipingChats] = useState(false);
  const [isClearingAudit, setIsClearingAudit] = useState(false);
  const [isResettingGraph, setIsResettingGraph] = useState(false);
  const [isExportingChats, setIsExportingChats] = useState(false);
  const [isExportingGraph, setIsExportingGraph] = useState(false);
  const [dataRefreshCount, setDataRefreshCount] = useState(0);
  const { toasts, showToast, dismissToast} = useToast();

  const loadData = useCallback(async () => {
    try {
      const [assetsData, networksData, auditData] = await Promise.all([
        listAssets(),
        listNetworks(),
        listAuditEvents({ page: 1, page_size: 50 }),
      ]);
      setAssets(assetsData);
      setNetworks(networksData);
      setAuditEvents(auditData.events);
      setAuditTotal(auditData.total);
      setSelectedNetworkId((current) => current ?? getNodeId(networksData[0] ?? {}));
      setDataRefreshCount((prev) => prev + 1);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load data";
      showToast(`API error: ${message}`, "error");
    } finally {
      setIsLoading(false);
    }
  }, [showToast]);

  const loadSessions = useCallback(async () => {
    try {
      const data = await listChatSessions();
      setSessions(data);
      setActiveSessionId((current) => {
        if (current && data.some((session) => session.session_id === current)) {
          return current;
        }
        return null;
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load chat sessions";
      showToast(`Chat error: ${message}`, "error");
    }
  }, [showToast]);

  const loadAppSettings = useCallback(async () => {
    setIsAppSettingsLoading(true);
    try {
      const settings = await getAppSettings();
      setAppSettings(settings);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load settings";
      showToast(`Settings error: ${message}`, "error");
    } finally {
      setIsAppSettingsLoading(false);
    }
  }, [showToast]);

  const handleUpdateAppSettings = useCallback(
    async (payload: AppSettingsUpdate) => {
      try {
        const updated = await updateAppSettings(payload);
        setAppSettings(updated);
        showToast("Settings saved", "success");
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to update settings";
        showToast(`Settings error: ${message}`, "error");
      }
    },
    [showToast]
  );

  const handleWipeChats = useCallback(async () => {
    if (!window.confirm("Delete all chat sessions? This cannot be undone.")) {
      return;
    }
    setIsWipingChats(true);
    try {
      await deleteAllChatSessions();
      setSessions([]);
      setActiveSessionId(null);
      showToast("All chats deleted", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to wipe chats";
      showToast(`Chat error: ${message}`, "error");
    } finally {
      setIsWipingChats(false);
    }
  }, [showToast]);

  const handleClearAudit = useCallback(async () => {
    if (!window.confirm("Clear all audit/event logs? This cannot be undone.")) {
      return;
    }
    setIsClearingAudit(true);
    try {
      await clearAuditEvents();
      setAuditEvents([]);
      setAuditTotal(0);
      showToast("Audit logs cleared", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to clear audit logs";
      showToast(`Audit error: ${message}`, "error");
    } finally {
      setIsClearingAudit(false);
    }
  }, [showToast]);

  const handleResetGraph = useCallback(async () => {
    if (!window.confirm("Reset all graph data? This will remove networks and assets.")) {
      return;
    }
    setIsResettingGraph(true);
    try {
      await resetGraph();
      setAssets([]);
      setNetworks([]);
      setSelectedNetworkId(null);
      showToast("Graph data cleared", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to reset graph data";
      showToast(`Graph error: ${message}`, "error");
    } finally {
      setIsResettingGraph(false);
    }
  }, [showToast]);

  const handleExportChats = useCallback(async () => {
    setIsExportingChats(true);
    try {
      const summaries = await listChatSessions();
      const sessionsData = await Promise.all(
        summaries.map((session) => getChatSession(session.session_id))
      );
      downloadJson(buildExportFilename("eidolon-chats"), sessionsData);
      showToast("Chat export ready", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to export chats";
      showToast(`Chat error: ${message}`, "error");
    } finally {
      setIsExportingChats(false);
    }
  }, [showToast]);

  const handleExportGraph = useCallback(async () => {
    setIsExportingGraph(true);
    try {
      const [assetsData, networksData] = await Promise.all([listAssets(500), listNetworks(500)]);
      downloadJson(buildExportFilename("eidolon-graph"), {
        assets: assetsData,
        networks: networksData,
      });
      showToast("Graph export ready", "success");
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to export graph data";
      showToast(`Graph error: ${message}`, "error");
    } finally {
      setIsExportingGraph(false);
    }
  }, [showToast]);

  const handleStartNewChat = useCallback(() => {
    setActiveSessionId(null);
    setActiveTab("chat");
  }, []);

  const handleCreateSession = useCallback(async (initialMessage: string) => {
    const title = buildSessionTitle(initialMessage);
    try {
      const session = await createChatSession(title);
      const summary = toSessionSummary(session);
      setSessions((prev) => [summary, ...prev.filter((item) => item.session_id !== summary.session_id)]);
      setActiveSessionId(session.session_id);
      setActiveTab("chat");
      return session;
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to create chat session";
      showToast(`Chat error: ${message}`, "error");
      return null;
    }
  }, [showToast]);

  const handleSelectSession = useCallback((sessionId: string) => {
    setActiveSessionId(sessionId);
    setActiveTab("chat");
  }, []);

  const handleDeleteSession = useCallback(
    async (sessionId: string) => {
      const previousSessions = sessions;
      const previousActive = activeSessionId;
      const nextSessions = previousSessions.filter((session) => session.session_id !== sessionId);
      setSessions(nextSessions);
      if (previousActive === sessionId) {
        setActiveSessionId(nextSessions[0]?.session_id ?? null);
      }
      try {
        await deleteChatSession(sessionId);
      } catch (err) {
        setSessions(previousSessions);
        setActiveSessionId(previousActive);
        const message = err instanceof Error ? err.message : "Failed to delete chat session";
        showToast(`Chat error: ${message}`, "error");
      }
    },
    [sessions, activeSessionId, showToast]
  );

  const handleSessionUpdated = useCallback((session: ChatSession) => {
    const summary = toSessionSummary(session);
    setSessions((prev) => [summary, ...prev.filter((item) => item.session_id !== summary.session_id)]);
  }, []);

  // Auto-collapse panels on narrow screens
  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth <= 1024) {
        setIsSidebarCollapsed(true);
      } else {
        setIsSidebarCollapsed(false);
      }

      if (window.innerWidth <= 768) {
        setIsRightPanelCollapsed(true);
      } else {
        setIsRightPanelCollapsed(false);
      }
    };

    // Set initial state
    handleResize();

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    loadAppSettings();
  }, [loadAppSettings]);

  useEffect(() => {
    const theme = appSettings?.theme.mode;
    if (!theme) {
      return;
    }
    document.documentElement.dataset.theme = theme;
  }, [appSettings?.theme.mode]);

  const selectedNetwork = useMemo(
    () => networks.find((network) => getNodeId(network) === selectedNetworkId) ?? null,
    [networks, selectedNetworkId]
  );

  return (
    <div className="layout">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
      <Sidebar 
        isCollapsed={isSidebarCollapsed}
        onToggle={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
        activeTab={activeTab}
        onTabChange={setActiveTab}
        sessions={sessions}
        activeSessionId={activeSessionId}
        onNewChat={handleStartNewChat}
        onSelectSession={handleSelectSession}
        onDeleteSession={handleDeleteSession}
      />
      
      <main className="main">
        {activeTab === "chat" && (
          <ChatInterface
            sessionId={activeSessionId}
            onSessionUpdated={handleSessionUpdated}
            onCreateSession={handleCreateSession}
          />
        )}
        {activeTab === "networks" && (
          <>
            <NetworkList
              networks={networks}
              assets={assets}
              selectedNetworkId={selectedNetworkId}
              onSelectNetwork={setSelectedNetworkId}
              isLoading={isLoading}
            />
            <StatsRow assets={assets} network={selectedNetwork} isLoading={isLoading} />
            <NetworkMap assets={assets} network={selectedNetwork} isLoading={isLoading} />
            <DeviceList assets={assets} network={selectedNetwork} isLoading={isLoading} />
          </>
        )}
        {activeTab === "graph" && <GraphView key="graph-view" showToast={showToast} refreshTrigger={dataRefreshCount} />}
        {activeTab === "audit" && (
          <EventLog events={auditEvents} isLoading={isLoading} limit={50} showFilters={true} total={auditTotal} />
        )}
        {activeTab === "settings" && (
          <SettingsPanel
            settings={appSettings}
            isLoading={isAppSettingsLoading}
            onSave={handleUpdateAppSettings}
            actions={{
              wipeChats: handleWipeChats,
              clearAudit: handleClearAudit,
              resetGraph: handleResetGraph,
              exportChats: handleExportChats,
              exportGraph: handleExportGraph,
            }}
            busy={{
              wipeChats: isWipingChats,
              clearAudit: isClearingAudit,
              resetGraph: isResettingGraph,
              exportChats: isExportingChats,
              exportGraph: isExportingGraph,
            }}
          />
        )}
      </main>
      
      <RightPanel
        isCollapsed={isRightPanelCollapsed}
        onToggle={() => setIsRightPanelCollapsed(!isRightPanelCollapsed)}
      >
        <ScannerControl
          onRefreshData={loadData}
          onOpenAudit={() => setActiveTab("audit")}
          showToast={showToast}
        />
      </RightPanel>
    </div>
  );
}
