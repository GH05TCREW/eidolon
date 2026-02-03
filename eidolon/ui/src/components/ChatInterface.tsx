import React, { useEffect, useMemo, useRef, useState } from "react";
import { Send, Square, Bot, User, Wrench, Kanban } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  appendChatMessage,
  appendChatMessageStream,
  cancelChatRequest,
  getChatSession,
  type ChatMessage,
  type ChatSession,
} from "../api";
import { useToast } from "./Toast";

type PlanItem = {
  id: number;
  text: string;
  status: string;
  result?: string;
};

type PlanState = {
  items: PlanItem[];
  currentIndex: number;
  completedCount: number;
};

type ChatInterfaceProps = {
  sessionId: string | null;
  onSessionUpdated?: (session: ChatSession) => void;
  onCreateSession?: (firstMessage: string) => Promise<ChatSession | null> | ChatSession | null;
};

export function ChatInterface({ sessionId, onSessionUpdated, onCreateSession }: ChatInterfaceProps) {
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isLoading, setIsLoading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [planAnchorId, setPlanAnchorId] = useState<string | null>(null);
  const [messageHistory, setMessageHistory] = useState<string[]>([]);
  const [historyIndex, setHistoryIndex] = useState(-1);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const currentRequestRef = useRef<string | null>(null);
  const currentSessionRef = useRef<string | null>(null);
  const suppressLoadRef = useRef<string | null>(null);
  const { showToast } = useToast();

  const upsertMessage = (msg: ChatMessage) => {
    setMessages((prev) => {
      const index = prev.findIndex((item) => item.message_id === msg.message_id);
      if (index === -1) {
        return [...prev, msg];
      }
      const next = [...prev];
      next[index] = msg;
      return next;
    });
  };

  const formatPayload = (value: unknown): string => {
    if (value === null || value === undefined) {
      return "";
    }
    if (typeof value === "string") {
      const trimmed = value.trim();
      if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
        try {
          const parsed = JSON.parse(trimmed);
          return JSON.stringify(parsed, null, 2);
        } catch {
          return value;
        }
      }
      return value;
    }
    try {
      return JSON.stringify(value, null, 2);
    } catch {
      return String(value);
    }
  };

  const summarizeText = (value: string, maxLength = 120) => {
    const trimmed = value.replace(/\s+/g, " ").trim();
    if (trimmed.length <= maxLength) {
      return trimmed;
    }
    return `${trimmed.slice(0, maxLength)}...`;
  };

  const getPlanState = (itemsRaw: unknown): PlanState => {
    if (!Array.isArray(itemsRaw)) {
      return { items: [], currentIndex: -1, completedCount: 0 };
    }
    const items = itemsRaw
      .map((item, index) => {
        if (typeof item === "string") {
          return { id: index + 1, text: item, status: "pending" };
        }
        if (item && typeof item === "object") {
          const record = item as Record<string, unknown>;
          const text = String(record.text || record.item || "");
          if (!text) {
            return null;
          }
          return {
            id: Number(record.id || index + 1),
            text,
            status: String(record.status || "pending"),
            result: record.result ? String(record.result) : undefined,
          };
        }
        return null;
      })
      .filter((item): item is PlanItem => Boolean(item));

    const isComplete = (status: string) => status === "complete" || status === "skip";
    const completedCount = items.filter((item) => isComplete(item.status)).length;
    const currentIndex = items.findIndex((item) => item.status === "pending");
    return {
      items,
      currentIndex,
      completedCount,
    };
  };

  const planWindowMessages = useMemo(() => {
    if (!planAnchorId) {
      return messages;
    }
    const anchorIndex = messages.findIndex((msg) => msg.message_id === planAnchorId);
    if (anchorIndex === -1) {
      return messages;
    }
    return messages.slice(anchorIndex + 1);
  }, [messages, planAnchorId]);

  const planState = useMemo(() => {
    for (let i = planWindowMessages.length - 1; i >= 0; i -= 1) {
      const msg = planWindowMessages[i];
      if (msg.role !== "tool") {
        continue;
      }
      if (msg.metadata?.tool_name !== "todo") {
        continue;
      }
      const result = msg.metadata?.result as Record<string, unknown> | undefined;
      const items = result?.items;
      const state = getPlanState(items);
      if (state.items.length > 0) {
        return state;
      }
    }
    return { items: [], currentIndex: -1, completedCount: 0 };
  }, [planWindowMessages]);

  const shouldHideMessage = (msg: ChatMessage) => {
    const kind = (msg.metadata?.kind as string | undefined) || "";
    if (kind === "plan") {
      return true;
    }
    if (kind === "internal" || msg.metadata?.cancelled) {
      return true;
    }
    if (msg.role === "tool" && msg.metadata?.tool_name === "todo") {
      return true;
    }
    if (kind === "tool_result" && msg.metadata?.tool_name === "todo") {
      return true;
    }
    if (kind === "tool_call") {
      const toolCalls = (msg.metadata?.tool_calls as Array<Record<string, unknown>>) || [];
      if (
        toolCalls.length > 0 &&
        toolCalls.every((call) => String(call.name || "") === "todo")
      ) {
        return true;
      }
    }
    return false;
  };

  const visibleMessages = useMemo(
    () => messages.filter((msg) => !shouldHideMessage(msg)),
    [messages]
  );

  const inputPlaceholder = "Ask Eidolon";

  const renderMessageBody = (msg: ChatMessage) => {
    const kind = (msg.metadata?.kind as string | undefined) || "";
    if (kind === "tool_call") {
      const toolCalls = (msg.metadata?.tool_calls as Array<Record<string, unknown>>) || [];
      const grouped = toolCalls.reduce<Record<string, number>>((acc, call) => {
        const name = String(call.name || "tool");
        acc[name] = (acc[name] || 0) + 1;
        return acc;
      }, {});
      const summaryLabel = Object.entries(grouped)
        .map(([name, count]) => (count > 1 ? `${name} x${count}` : name))
        .join(", ");
      return (
        <details className="tool-details">
          <summary className="tool-summary">
            <span className="tool-summary-title">Tool call</span>
            <span className="tool-summary-name">{summaryLabel || "tool"}</span>
          </summary>
          <div className="tool-block">
            {toolCalls.map((call, index) => {
              const name = String(call.name || "tool");
              const args = call.arguments || {};
              return (
                <div key={`${name}-${index}`} className="tool-entry">
                  <div className="tool-title">{name}</div>
                  <pre>{formatPayload(args)}</pre>
                </div>
              );
            })}
          </div>
        </details>
      );
    }

    if (kind === "tool_result") {
      const toolName = String(msg.metadata?.tool_name || "tool");
      const success = msg.metadata?.success !== false;
      const payload = msg.metadata?.result || msg.metadata?.error || msg.content;
      const preview = summarizeText(formatPayload(payload), 140);
      return (
        <details className="tool-details">
          <summary className="tool-summary">
            <span className="tool-summary-title">Tool result</span>
            <span className={`tool-summary-name ${success ? "ok" : "error"}`}>{toolName}</span>
            <span className="tool-summary-preview">{preview}</span>
          </summary>
          <div className="tool-block">
            <div className={`tool-title ${success ? "ok" : "error"}`}>{toolName}</div>
            <pre>{formatPayload(payload)}</pre>
          </div>
        </details>
      );
    }

    return (
      <div className="message-text">
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {msg.content}
        </ReactMarkdown>
      </div>
    );
  };

  const labelForKind = (kind: string) => {
    switch (kind) {
      case "thinking":
        return "Thinking";
      case "warning":
        return "Warning";
      case "error":
        return "Error";
      default:
        return "";
    }
  };

  useEffect(() => {
    let active = true;
    if (abortControllerRef.current) {
      // Only abort if the session ID has changed to something other than what we're currently processing
      // This prevents aborting the initial request when a new session is created
      if (currentSessionRef.current !== sessionId) {
        abortControllerRef.current.abort();
        abortControllerRef.current = null;
        currentRequestRef.current = null;
        currentSessionRef.current = null;
        setIsSending(false);
      }
    }
    setPlanAnchorId(null);
    if (!sessionId) {
      currentSessionRef.current = null;
      setMessages([]);
      setIsLoading(false);
      return () => {
        active = false;
      };
    }
    // Update ref to match new session
    currentSessionRef.current = sessionId;
    setIsLoading(true);
    const loadSession = async () => {
      try {
        const session = await getChatSession(sessionId);
        if (!active) {
          return;
        }
        if (suppressLoadRef.current === sessionId && session.messages.length === 0) {
          return;
        }
        setMessages(session.messages);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to load chat session";
        if (active) {
          showToast(`Chat error: ${message}`, "error");
        }
      } finally {
        if (active) {
          setIsLoading(false);
        }
      }
    };
    loadSession();
    return () => {
      active = false;
    };
  }, [sessionId, showToast, onSessionUpdated]);

  const refreshSession = async (activeSessionId: string) => {
    const session = await getChatSession(activeSessionId);
    const shouldUpdate =
      sessionId === activeSessionId || currentSessionRef.current === activeSessionId;
    if (!shouldUpdate) {
      return session;
    }
    setMessages(session.messages);
    if (onSessionUpdated) {
      onSessionUpdated(session);
    }
    return session;
  };

  useEffect(() => {
    if (messages.length === 0) {
      return;
    }
    const lastUser = [...messages].reverse().find((msg) => msg.role === "user");
    if (!lastUser) {
      return;
    }
    const anchorExists = planAnchorId
      ? messages.some((msg) => msg.message_id === planAnchorId)
      : false;
    if (!planAnchorId || !anchorExists) {
      setPlanAnchorId(lastUser.message_id);
    }
  }, [messages, planAnchorId]);

  // Auto-scroll to bottom when messages change
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [visibleMessages]);

  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed || isSending) {
      return;
    }
    setIsSending(true);

    let activeSessionId = sessionId;
    let createdSession = false;
    if (!activeSessionId) {
      if (!onCreateSession) {
        showToast("Unable to start a new chat", "error");
        setIsSending(false);
        return;
      }
      let created: ChatSession | null = null;
      try {
        created = await onCreateSession(trimmed);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to start a new chat";
        showToast(message, "error");
        setIsSending(false);
        return;
      }
      activeSessionId = created?.session_id ?? null;
      if (!activeSessionId) {
        showToast("Failed to start a new chat", "error");
        setIsSending(false);
        return;
      }
      createdSession = true;
    }

    const requestId = `req_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    currentRequestRef.current = requestId;
    currentSessionRef.current = activeSessionId;
    if (createdSession) {
      suppressLoadRef.current = activeSessionId;
    }
    const userMsg = { role: "user" as const, content: trimmed };
    const optimistic = {
      message_id: `temp-${Date.now()}`,
      role: "user" as const,
      content: trimmed,
      timestamp: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, optimistic]);
    setPlanAnchorId(optimistic.message_id);
    
    // Add to message history
    setMessageHistory((prev) => [...prev, trimmed]);
    setHistoryIndex(-1);
    
    setInput("");
    const abortController = new AbortController();
    abortControllerRef.current = abortController;

    let receivedAny = false;
    try {
      await appendChatMessageStream(
        activeSessionId,
        userMsg,
        (event) => {
          if (event.type === "message") {
            receivedAny = true;
            upsertMessage(event.message);
          }
        },
        abortController.signal,
        requestId
      );
      try {
        await refreshSession(activeSessionId);
      } catch {
        // Ignore refresh errors; stream already rendered messages
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") {
        try {
          await refreshSession(activeSessionId);
        } catch {
          // Ignore refresh errors after abort
        }
        return;
      }
      const message = err instanceof Error ? err.message : "Request failed";
      if (!receivedAny) {
        try {
          const session = await appendChatMessage(activeSessionId, {
            ...userMsg,
            request_id: requestId,
          });
          setMessages(session.messages);
          if (onSessionUpdated) {
            onSessionUpdated(session);
          }
        } catch {
          setMessages((prev) => [
            ...prev,
            {
              message_id: `temp-${Date.now() + 1}`,
              role: "assistant",
              content: `Unable to complete request: ${message}`,
              timestamp: new Date().toISOString(),
            },
          ]);
          showToast(`Query error: ${message}`, "error");
        }
      } else {
        showToast(`Streaming error: ${message}`, "warning");
      }
    } finally {
      currentRequestRef.current = null;
      currentSessionRef.current = null;
      suppressLoadRef.current = null;
      abortControllerRef.current = null;
      setIsSending(false);
    }
  };

  const handleStop = async () => {
    const activeSessionId = currentSessionRef.current;
    if (!activeSessionId || !abortControllerRef.current || !currentRequestRef.current) {
      return;
    }
    const requestId = currentRequestRef.current;
    abortControllerRef.current.abort();
    try {
      const result = await cancelChatRequest(activeSessionId, requestId);
      await refreshSession(activeSessionId);
      if (result.status === "cancelled") {
        showToast("Request cancelled", "warning");
      } else {
        showToast("No active request to cancel", "info");
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to cancel request";
      showToast(message, "error");
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (messageHistory.length === 0) return;
      
      const newIndex = historyIndex === -1 
        ? messageHistory.length - 1 
        : Math.max(0, historyIndex - 1);
      
      setHistoryIndex(newIndex);
      setInput(messageHistory[newIndex]);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (historyIndex === -1) return;
      
      const newIndex = historyIndex + 1;
      if (newIndex >= messageHistory.length) {
        setHistoryIndex(-1);
        setInput("");
      } else {
        setHistoryIndex(newIndex);
        setInput(messageHistory[newIndex]);
      }
    }
  };

  return (
    <div className="chat-view">
      {planState.items.length > 0 && (
        <div className="plan-dock">
          <details className="plan-details">
            <summary className="plan-summary">
              <span className="plan-title">Todo</span>
              <span className="plan-progress">
                {planState.completedCount}/{planState.items.length}
              </span>
              <span className="plan-current">
                {planState.currentIndex >= 0
                  ? planState.items[planState.currentIndex]?.text
                  : "All steps complete"}
              </span>
            </summary>
            <ol className="plan-list">
              {planState.items.map((item, index) => {
                const isCurrent = index === planState.currentIndex;
                const status = item.status;
                return (
                  <li
                    key={item.id}
                    className={`plan-step ${status} ${isCurrent ? "current" : ""}`}
                  >
                    <span className="plan-step-title">{item.text}</span>
                    {item.result ? (
                      <span className="plan-step-result">{item.result}</span>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </details>
        </div>
      )}
      <div className="chat-scroll-container">
        <div className="chat-content">
          {visibleMessages.length === 0 && !isSending && (
            <div className="chat-empty">
              <Kanban className="chat-empty-icon" strokeWidth={1.5} style={{ transform: 'rotate(270deg)' }} />
            </div>
          )}
          
          {visibleMessages.map((msg) => {
            const kind = (msg.metadata?.kind as string | undefined) || "";
            const kindClass = kind && kind !== "message" ? kind : "";
            const label = labelForKind(kind);
            return (
            <div
              key={msg.message_id}
              className={`message ${msg.role} ${kindClass}`}
            >
              <div className="message-content">
                {label ? <div className="message-label">{label}</div> : null}
                {renderMessageBody(msg)}
              </div>
            </div>
            );
          })}
          <div ref={messagesEndRef} />
        </div>
      </div>
      
      <div className="chat-footer">
        <form className="chat-input-area" onSubmit={handleSend}>
          <input 
            type="text" 
            className="chat-input" 
            placeholder={inputPlaceholder}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={isLoading}
          />
          {isSending ? (
            <button
              type="button"
              className="chat-send-btn chat-stop-btn"
              onClick={handleStop}
              title="Stop AI"
            >
              <Square size={18} />
            </button>
          ) : (
            <button
              type="submit"
              className="chat-send-btn"
              disabled={isLoading}
              title="Send message"
            >
              <Send size={18} />
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
