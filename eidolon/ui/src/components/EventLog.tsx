import React, { useState } from "react";
import { type AuditEvent, listAuditEvents } from "../api";

interface EventLogProps {
  events: AuditEvent[];
  isLoading?: boolean;
  limit?: number;
  showFilters?: boolean;
  total?: number;
}

function formatRelativeTime(timestamp: string): string {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  if (Number.isNaN(then)) {
    return "unknown";
  }
  const diffSeconds = Math.max(0, Math.floor((now - then) / 1000));
  if (diffSeconds < 60) {
    return `${diffSeconds}s ago`;
  }
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) {
    return `${diffMinutes}m ago`;
  }
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d ago`;
}

function describeEvent(event: AuditEvent): string {
  const details = event.details || {};
  const eventsProcessed =
    typeof details.events_processed === "number" ? details.events_processed : 0;
  const totalEvents =
    typeof details.total_events === "number" ? details.total_events : 0;
  const accepted = typeof details.accepted === "number" ? details.accepted : 0;
  const steps = typeof details.steps === "number" ? details.steps : 0;
  const pathsFound = typeof details.paths_found === "number" ? details.paths_found : 0;
  const status = typeof details.status === "string" ? details.status : event.status;
  const question = typeof details.question === "string" ? details.question : "request";
  const collectors = Array.isArray(details.collectors) ? details.collectors.join(", ") : "";
  const configSummary = typeof details.config_summary === "string" ? details.config_summary : "";
  
  switch (event.event_type) {
    case "collector.scan.started":
      return `Scan started: ${collectors}`;
    case "collector.scan.complete":
      return configSummary ? `${configSummary} (${totalEvents} events)` : `Scan complete (${totalEvents} events)`;
    case "collector.scan.cancelled":
      return configSummary ? `Scan cancelled: ${configSummary}` : "Scan cancelled";
    case "collector.scan.failed":
      return "Scan failed";
    case "collector.scan":
      return `Collector scan (${eventsProcessed} events)`;
    case "ingest":
      return `Ingested ${accepted} events`;
    case "plan":
      return `Plan generated (${steps} steps)`;
    case "execute":
      return `Execution ${status}`;
    case "query":
      return `Query: ${question}`;
    case "query.paths":
      return `Path query (${pathsFound} paths)`;
    default:
      // Skip collector.* events that are per-collector (redundant with scan.complete)
      if (event.event_type.startsWith("collector.") && !event.event_type.includes("scan")) {
        return null; // Filter out in component
      }
      return event.event_type.replace(/\./g, " ");
  }
}

export function EventLog({ events: initialEvents, isLoading = false, limit = 15, showFilters = false, total = 0 }: EventLogProps) {
  const [events, setEvents] = useState(initialEvents);
  const [filteredTotal, setFilteredTotal] = useState(total);
  const [page, setPage] = useState(1);
  const [eventTypeFilter, setEventTypeFilter] = useState<string>("");
  const [dateRangeFilter, setDateRangeFilter] = useState<string>("all");
  const [loading, setLoading] = useState(false);
  const pageSize = showFilters ? 50 : limit;
  
  // Update local events when props change
  React.useEffect(() => {
    setEvents(initialEvents);
  }, [initialEvents]);
  
  const applyFilters = async () => {
    setLoading(true);
    try {
      let start_date: string | undefined;
      let end_date: string | undefined;
      
      if (dateRangeFilter === "24h") {
        start_date = new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString();
      } else if (dateRangeFilter === "7d") {
        start_date = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString();
      } else if (dateRangeFilter === "30d") {
        start_date = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString();
      }
      
      const response = await listAuditEvents({
        page,
        page_size: pageSize,
        event_type: eventTypeFilter || undefined,
        start_date,
        end_date,
      });
      setEvents(response.events);
      setFilteredTotal(response.total);
    } catch (err) {
      console.error("Failed to fetch filtered events:", err);
    } finally {
      setLoading(false);
    }
  };
  
  React.useEffect(() => {
    if (showFilters) {
      applyFilters();
    }
  }, [page, eventTypeFilter, dateRangeFilter, showFilters]);
  
  const recentLogs = showFilters ? events : [...events]
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, limit);
  
  const eventTypes = Array.from(new Set(initialEvents.map(e => e.event_type)));
  const totalPages = Math.ceil((showFilters ? filteredTotal : (total || events.length)) / pageSize);
  
  return (
    <div className="event-log-section">
      <div className="section-title">Event Logs</div>
      
      {showFilters && (
        <div style={{ marginBottom: "1rem", display: "flex", gap: "1rem", flexWrap: "wrap" }}>
          <div>
            <label style={{ marginRight: "0.5rem", fontSize: "0.9rem" }}>Event Type:</label>
            <select 
              value={eventTypeFilter} 
              onChange={(e) => { setEventTypeFilter(e.target.value); setPage(1); }}
              style={{ padding: "0.3rem", borderRadius: "4px", border: "1px solid #ddd" }}
            >
              <option value="">All Types</option>
              {eventTypes.map(type => (
                <option key={type} value={type}>{type}</option>
              ))}
            </select>
          </div>
          
          <div>
            <label style={{ marginRight: "0.5rem", fontSize: "0.9rem" }}>Date Range:</label>
            <select 
              value={dateRangeFilter} 
              onChange={(e) => { setDateRangeFilter(e.target.value); setPage(1); }}
              style={{ padding: "0.3rem", borderRadius: "4px", border: "1px solid #ddd" }}
            >
              <option value="all">All Time</option>
              <option value="24h">Last 24 Hours</option>
              <option value="7d">Last 7 Days</option>
              <option value="30d">Last 30 Days</option>
            </select>
          </div>
          
          {totalPages > 1 && (
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: "0.25rem", fontSize: "0.8rem" }}>
              <button 
                onClick={() => setPage(p => Math.max(1, p - 1))} 
                disabled={page === 1}
                style={{ padding: "0.15rem 0.4rem", cursor: page === 1 ? "not-allowed" : "pointer", fontSize: "0.75rem" }}
              >
                ←
              </button>
              <span style={{ fontSize: "0.75rem", opacity: 0.7 }}>Page {page} of {totalPages}</span>
              <button 
                onClick={() => setPage(p => Math.min(totalPages, p + 1))} 
                disabled={page === totalPages}
                style={{ padding: "0.15rem 0.4rem", cursor: page === totalPages ? "not-allowed" : "pointer", fontSize: "0.75rem" }}
              >
                →
              </button>
            </div>
          )}
        </div>
      )}
      
      {(isLoading || loading) && <div className="text-muted">Loading events...</div>}
      {!isLoading && !loading && recentLogs.length === 0 && (
        <div className="text-muted">No events yet.</div>
      )}
      {!isLoading && !loading && recentLogs.length > 0 && (
        <ul className="log-list">
          {recentLogs.map((event) => {
            const message = describeEvent(event);
            if (!message) return null; // Skip filtered events
            const time = formatRelativeTime(event.timestamp);
            return (
              <li key={event.audit_id ?? event.id ?? message} className="log-item" title={message}>
                <span className="log-icon"></span>
                <span className="log-msg">{message}</span>
                <span className="log-time">({time})</span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
