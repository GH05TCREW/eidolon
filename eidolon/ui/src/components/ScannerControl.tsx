import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Loader2,
  Play,
  Square,
  X,
  XCircle,
} from "lucide-react";
import {
  API_BASE,
  cancelScan,
  getCollectorConfig,
  isIpv4,
  startScan,
  updateCollectorConfig,
  type ScannerConfig,
} from "../api";

type ToastType = "error" | "warning" | "info" | "success";

type ScannerControlProps = {
  onRefreshData: () => Promise<void>;
  onOpenAudit: () => void;
  showToast: (message: string, type?: ToastType, duration?: number) => void;
};

const DEFAULT_CONFIG: ScannerConfig = {
  network_cidrs: ["192.168.1.0/24"],
  ports: [21, 22, 23, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995, 3306, 3389, 5432, 8080, 8443],
  port_preset: "normal",
  options: {
    ping_concurrency: 128,
    port_scan_workers: 32,
    dns_resolution: true,
    aggressive: false,
  },
};

const PORT_PRESETS = [
  { value: "fast", label: "Fast (common web ports)", ports: [80, 443] },
  { value: "normal", label: "Normal (common services)", ports: [21, 22, 23, 25, 53, 80, 110, 143, 443, 465, 587, 993, 995, 3306, 3389, 5432, 8080, 8443] },
  { value: "full", label: "Full (all 65535 ports)", ports: [] },
  { value: "custom", label: "Custom (ranges supported)", ports: [] },
];

const ipToNumber = (ip: string): number | null => {
  if (!isIpv4(ip)) {
    return null;
  }
  const [a, b, c, d] = ip.split(".").map((part) => Number(part));
  return (((a << 24) >>> 0) + (b << 16) + (c << 8) + d) >>> 0;
};

const parseCidr = (cidr: string): { start: number; end: number } | null => {
  const parts = cidr.split("/");
  if (parts.length !== 2) {
    return null;
  }
  const base = ipToNumber(parts[0]);
  const bits = Number(parts[1]);
  if (base === null || !Number.isInteger(bits) || bits < 0 || bits > 32) {
    return null;
  }
  const mask = bits === 0 ? 0 : (~0 << (32 - bits)) >>> 0;
  const start = base & mask;
  const size = Math.max(1, 2 ** (32 - bits));
  const end = start + size - 1;
  return { start, end };
};

const parseTargetRange = (value: string): { start: number; end: number } | null => {
  if (value.includes("/")) {
    return parseCidr(value);
  }
  if (value.includes("-")) {
    const [startRaw, endRaw] = value.split("-", 2);
    const start = ipToNumber(startRaw);
    if (start === null) {
      return null;
    }
    let end = ipToNumber(endRaw);
    if (end === null && /^\d+$/.test(endRaw)) {
      const parts = startRaw.split(".");
      if (parts.length !== 4) {
        return null;
      }
      end = ipToNumber(`${parts[0]}.${parts[1]}.${parts[2]}.${endRaw}`);
    }
    if (end === null || end < start) {
      return null;
    }
    return { start, end };
  }
  const single = ipToNumber(value);
  if (single === null) {
    return null;
  }
  return { start: single, end: single };
};

const validateTargetValue = (value: string): string | null => {
  if (!value.trim()) {
    return "Target cannot be empty";
  }
  if (!parseTargetRange(value.trim())) {
    return "Invalid CIDR, IP, or range";
  }
  return null;
};

const validateTargetsList = (targets: string[]): string | null => {
  if (targets.length === 0) {
    return "At least one target is required";
  }
  if (targets.length > 50) {
    return "Maximum of 50 targets allowed";
  }
  const normalized = targets.map((target) => target.trim()).filter(Boolean);
  const unique = new Set(normalized);
  if (unique.size !== normalized.length) {
    return "Duplicate targets are not allowed";
  }
  const ranges: { start: number; end: number; target: string }[] = [];
  for (const target of normalized) {
    const parsed = parseTargetRange(target);
    if (!parsed) {
      return `Invalid target: ${target}`;
    }
    ranges.push({ ...parsed, target });
  }
  ranges.sort((a, b) => a.start - b.start);
  for (let i = 1; i < ranges.length; i += 1) {
    const prev = ranges[i - 1];
    const current = ranges[i];
    if (current.start <= prev.end) {
      return `Target ${current.target} overlaps ${prev.target}`;
    }
  }
  return null;
};

const parsePortInput = (value: string): { ports: number[]; error: string | null } => {
  const tokens = value
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean);
  const ports: number[] = [];
  const seen = new Set<number>();

  for (const token of tokens) {
    if (token.includes("-")) {
      const [startRaw, endRaw] = token.split("-", 2);
      const start = Number(startRaw);
      const end = Number(endRaw);
      if (!Number.isInteger(start) || !Number.isInteger(end) || start < 1 || end > 65535 || end < start) {
        return { ports: [], error: "Invalid port range" };
      }
      for (let port = start; port <= end; port += 1) {
        if (seen.has(port)) {
          return { ports: [], error: "Duplicate ports are not allowed" };
        }
        seen.add(port);
        ports.push(port);
        if (ports.length > 1000) {
          return { ports: [], error: "Maximum of 1000 ports allowed" };
        }
      }
      continue;
    }
    const port = Number(token);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      return { ports: [], error: "Ports must be between 1 and 65535" };
    }
    if (seen.has(port)) {
      return { ports: [], error: "Duplicate ports are not allowed" };
    }
    seen.add(port);
    ports.push(port);
  }

  if (ports.length === 0) {
    return { ports: [], error: "Custom ports are required" };
  }

  return { ports, error: null };
};

const formatRelativeTime = (timestamp?: string | null): string => {
  if (!timestamp) {
    return "Never";
  }
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  if (Number.isNaN(then)) {
    return "Unknown";
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
};

export function ScannerControl({ onRefreshData, onOpenAudit, showToast }: ScannerControlProps) {
  const [draftConfig, setDraftConfig] = useState<ScannerConfig>(DEFAULT_CONFIG);
  const [savedConfig, setSavedConfig] = useState<ScannerConfig | null>(null);
  const [pendingDraft, setPendingDraft] = useState<ScannerConfig | null>(null);
  const savedConfigRef = useRef<ScannerConfig | null>(null);

  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const [targetInput, setTargetInput] = useState("");
  const [targetInputError, setTargetInputError] = useState<string | null>(null);
  const [portInput, setPortInput] = useState("");
  const [portInputError, setPortInputError] = useState<string | null>(null);
  const [portInputTouched, setPortInputTouched] = useState(false);

  const [isScanning, setIsScanning] = useState(false);
  const [scanTaskId, setScanTaskId] = useState<string | null>(null);
  const [scanEvents, setScanEvents] = useState(0);
  const [scanOutput, setScanOutput] = useState<string[]>([]);
  const [isCancelling, setIsCancelling] = useState(false);

  const eventSourceRef = useRef<EventSource | null>(null);
  const eventsByCollectorRef = useRef<Record<string, number>>({});
  const terminalRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    savedConfigRef.current = savedConfig;
  }, [savedConfig]);

  // Auto-scroll terminal when new output arrives
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.scrollTop = terminalRef.current.scrollHeight;
    }
  }, [scanOutput]);

  useEffect(() => {
    let isMounted = true;
    const loadConfig = async () => {
      setIsLoading(true);
      try {
        const config = await getCollectorConfig();
        const normalized: ScannerConfig = {
          ...DEFAULT_CONFIG,
          ...config,
          options: { ...DEFAULT_CONFIG.options, ...config.options },
        };
        if (!isMounted) {
          return;
        }
        setSavedConfig(normalized);
        setDraftConfig(normalized);
        setPortInput(normalized.port_preset === "custom" ? normalized.ports.join(",") : "");
        setLoadError(null);
      } catch (err) {
        if (!isMounted) {
          return;
        }
        setLoadError("Failed to load scanner config. Using defaults.");
        setSavedConfig(DEFAULT_CONFIG);
        setDraftConfig(DEFAULT_CONFIG);
        setPortInput("");
      } finally {
        if (isMounted) {
          setIsLoading(false);
        }
      }
    };
    loadConfig();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    if (draftConfig.port_preset !== "custom") {
      setPortInput("");
      setPortInputError(null);
      setPortInputTouched(false);
      return;
    }
    setPortInput(draftConfig.ports.join(","));
    setPortInputTouched(false);
  }, [draftConfig.port_preset, draftConfig.ports]);

  useEffect(() => {
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, []);

  // Refresh relative timestamps every 30 seconds
  useEffect(() => {
    const interval = setInterval(() => {
      // No longer needed - removed history
    }, 30000);
    return () => clearInterval(interval);
  }, []);

  const targetsError = useMemo(
    () => validateTargetsList(draftConfig.network_cidrs),
    [draftConfig.network_cidrs]
  );

  const portError = useMemo(() => {
    if (draftConfig.port_preset !== "custom") {
      return null;
    }
    // Always validate that custom preset has ports
    if (draftConfig.ports.length === 0) {
      return "Custom ports are required";
    }
    // Only validate input format if user has tried to edit
    if (!portInputTouched) {
      return null;
    }
    return parsePortInput(portInput).error;
  }, [draftConfig.port_preset, draftConfig.ports.length, portInput, portInputTouched]);

  const isConfigValid = !targetsError && !portError;

  const isDirty = useMemo(() => {
    if (!savedConfig) {
      return false;
    }
    return JSON.stringify(savedConfig) !== JSON.stringify(draftConfig);
  }, [savedConfig, draftConfig]);

  const inputsDisabled = isLoading;

  const saveConfig = useCallback(
    async (nextConfig: ScannerConfig) => {
      if (isSaving) {
        return;
      }
      setIsSaving(true);
      try {
        const updated = await updateCollectorConfig(nextConfig);
        setSavedConfig(updated);
        setDraftConfig(updated);
        setPendingDraft(null);
        setSaveError(null);
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to save configuration";
        setSaveError(message);
        setPendingDraft(nextConfig);
        const fallback = savedConfigRef.current;
        if (fallback) {
          setDraftConfig(fallback);
        }
        showToast(`Failed to save configuration: ${message}`, "error");
      } finally {
        setIsSaving(false);
      }
    },
    [isSaving, showToast]
  );

  useEffect(() => {
    if (!savedConfig || !isDirty || !isConfigValid || isSaving) {
      return undefined;
    }
    const timer = window.setTimeout(() => {
      saveConfig(draftConfig);
    }, 1000);
    return () => window.clearTimeout(timer);
  }, [savedConfig, isDirty, isConfigValid, isSaving, draftConfig, saveConfig]);

  const handleAddTarget = useCallback(() => {
    const trimmed = targetInput.trim();
    if (!trimmed) {
      setTargetInputError("Target cannot be empty");
      return;
    }
    const inputError = validateTargetValue(trimmed);
    if (inputError) {
      setTargetInputError(inputError);
      return;
    }
    const nextTargets = [...draftConfig.network_cidrs, trimmed];
    const listError = validateTargetsList(nextTargets);
    if (listError) {
      setTargetInputError(listError);
      return;
    }
    setDraftConfig((prev) => ({ ...prev, network_cidrs: nextTargets }));
    setTargetInput("");
    setTargetInputError(null);
  }, [draftConfig.network_cidrs, targetInput]);

  const handleRemoveTarget = (target: string) => {
    setDraftConfig((prev) => ({
      ...prev,
      network_cidrs: prev.network_cidrs.filter((item) => item !== target),
    }));
  };

  const handlePresetChange = (value: string) => {
    const preset = PORT_PRESETS.find((option) => option.value === value);
    if (!preset) {
      return;
    }
    setDraftConfig((prev) => ({
      ...prev,
      port_preset: preset.value,
      ports: preset.value === "custom" ? [] : preset.ports,
    }));
    if (preset.value === "custom") {
      setPortInput("");
    }
    setPortInputError(null);
  };

  const handleApplyCustomPorts = () => {
    setPortInputTouched(true);
    // Don't validate if input matches current config
    const currentPortsString = draftConfig.ports.join(",");
    if (portInput.trim() === currentPortsString) {
      return;
    }
    const parsed = parsePortInput(portInput);
    if (parsed.error) {
      setPortInputError(parsed.error);
      return;
    }
    setDraftConfig((prev) => ({ ...prev, ports: parsed.ports }));
    setPortInputError(null);
  };

  const closeEventSource = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }
  }, []);

  const handleEvent = useCallback(
    (taskId: string, payload: any) => {
      if (payload?.payload?.task_id && payload.payload.task_id !== taskId) {
        return;
      }
      if (payload?.status === "progress") {
        // Capture scan output
        if (payload.payload?.output) {
          setScanOutput(prev => [...prev.slice(-100), payload.payload.output]);
        }
        const collector = payload.payload?.collector;
        const eventsProcessed = Number(payload.payload?.events_processed ?? 0);
        if (collector) {
          eventsByCollectorRef.current[collector] = eventsProcessed;
          const total = Object.values(eventsByCollectorRef.current).reduce(
            (sum, value) => sum + value,
            0
          );
          setScanEvents(total);
        }
      }
      if (payload?.status === "complete" || payload?.status === "partial" || payload?.status === "failed") {
        setScanEvents(Number(payload.payload?.total_events ?? scanEvents));
        setIsScanning(false);
        setIsCancelling(false);
        setScanTaskId(null);
        closeEventSource();
        onRefreshData();
        showToast(
          payload.status === "complete" ? "Scan completed" : "Scan finished with issues",
          payload.status === "complete" ? "success" : "warning",
          3000
        );
      }
      if (payload?.status === "cancelled") {
        setIsScanning(false);
        setIsCancelling(false);
        setScanTaskId(null);
        closeEventSource();
        onRefreshData();
        showToast("Scan cancelled", "info", 2000);
      }
    },
    [closeEventSource, onRefreshData, scanEvents, showToast]
  );

  const openEventSource = useCallback(
    (taskId: string) => {
      closeEventSource();
      const eventSource = new EventSource(`${API_BASE}/tasks/stream`);
      eventSourceRef.current = eventSource;

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.event_type !== "collector.scan") {
            return;
          }
          handleEvent(taskId, data);
        } catch (err) {
          console.error("Error parsing SSE event:", err);
        }
      };

      eventSource.onerror = () => {
        closeEventSource();
        if (isScanning) {
          showToast("Lost connection to scan stream", "error");
          setIsScanning(false);
          setIsCancelling(false);
        }
      };
    },
    [closeEventSource, handleEvent, isScanning, showToast]
  );

  const handleRunScan = useCallback(async () => {
    if (!isConfigValid || isScanning || inputsDisabled) {
      return;
    }
    setIsScanning(true);
    setScanOutput([]);
    setScanEvents(0);
    setIsCancelling(false);
    eventsByCollectorRef.current = {};

    try {
      const response = await startScan();
      setScanTaskId(response.task_id);
      openEventSource(response.task_id);
      showToast("Scan started", "info", 2000);
      onRefreshData();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to start scan";
      showToast(`Scan error: ${message}`, "error");
      setIsScanning(false);
    }
  }, [inputsDisabled, isConfigValid, isScanning, onRefreshData, openEventSource, showToast]);

  const handleCancelScan = useCallback(async () => {
    if (!scanTaskId || isCancelling) {
      return;
    }
    setIsCancelling(true);
    try {
      await cancelScan(scanTaskId);
      showToast("Cancelling scan...", "info", 1500);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to cancel scan";
      showToast(`Scan error: ${message}`, "error");
      setIsCancelling(false);
    }
  }, [scanTaskId, isCancelling, showToast]);

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
        event.preventDefault();
        handleRunScan();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [handleRunScan]);

  const renderStatusBadge = (status?: string | null) => {
    if (!status) {
      return null;
    }
    const normalized = status.toLowerCase();
    if (normalized === "complete") {
      return (
        <span className="scanner-status-badge success">
          <CheckCircle2 size={12} /> Complete
        </span>
      );
    }
    if (normalized === "partial") {
      return (
        <span className="scanner-status-badge warning">
          <AlertTriangle size={12} /> Partial
        </span>
      );
    }
    if (normalized === "failed") {
      return (
        <span className="scanner-status-badge danger">
          <XCircle size={12} /> Failed
        </span>
      );
    }
    if (normalized === "cancelled") {
      return (
        <span className="scanner-status-badge muted">
          <XCircle size={12} /> Cancelled
        </span>
      );
    }
    return (
      <span className="scanner-status-badge muted">
        <Loader2 size={12} /> {status}
      </span>
    );
  };

  const largeScanWarning = useMemo(() => {
    if (draftConfig.port_preset !== "full") {
      return null;
    }
    const ranges = draftConfig.network_cidrs
      .map((target) => parseTargetRange(target.trim()))
      .filter(Boolean) as { start: number; end: number }[];
    const totalHosts = ranges.reduce((sum, range) => sum + (range.end - range.start + 1), 0);
    if (totalHosts >= 4096) {
      return "All ports on large ranges can take hours.";
    }
    return null;
  }, [draftConfig.network_cidrs, draftConfig.port_preset]);

  // Summary text helpers
  const targetsSummary = useMemo(() => {
    const count = draftConfig.network_cidrs.length;
    if (count === 0) return "No targets";
    if (count === 1) return draftConfig.network_cidrs[0];
    return `${draftConfig.network_cidrs[0]} +${count - 1} more`;
  }, [draftConfig.network_cidrs]);

  const portsSummary = useMemo(() => {
    const preset = PORT_PRESETS.find(p => p.value === draftConfig.port_preset);
    if (preset && draftConfig.port_preset !== "custom") {
      return preset.label;
    }
    const ports = draftConfig.ports;
    if (ports.length === 0) return "No ports";
    if (ports.length <= 5) return ports.join(", ");
    return `${ports.slice(0, 3).join(", ")} +${ports.length - 3} more`;
  }, [draftConfig.port_preset, draftConfig.ports]);

  return (
    <div className="scanner-panel">
      {loadError && <div className="scanner-banner">{loadError}</div>}

      {isLoading ? (
        <div className="scanner-skeleton">
          <div className="scanner-skeleton-line" />
          <div className="scanner-skeleton-line" />
          <div className="scanner-skeleton-line" />
        </div>
      ) : (
        <>
          <div className="scanner-config-sections">
            <div className="scanner-run-row">
              <button
                className="scanner-run-btn"
              onClick={isScanning ? handleCancelScan : handleRunScan}
              disabled={isScanning ? isCancelling : (!isConfigValid || inputsDisabled)}
            >
              {isScanning ? (
                <>
                  <Square size={14} /> SCANNING
                </>
              ) : (
                <>
                  <Play size={14} /> Run Scan
                </>
              )}
            </button>
          </div>

          <details className="scanner-section">
            <summary className="scanner-section-title">
              <ChevronRight size={14} className="scanner-chevron" />
              <span>Network Targets ({draftConfig.network_cidrs.length})</span>
            </summary>
            <div className="scanner-section-content">
              <div className={`scanner-chip-input ${targetInputError || targetsError ? "error" : ""}`}>
                {draftConfig.network_cidrs.map((target) => (
                  <span key={target} className="scanner-chip">
                    {target}
                    <button
                      type="button"
                      className="scanner-chip-remove"
                      onClick={() => handleRemoveTarget(target)}
                      disabled={inputsDisabled}
                    >
                      <X size={12} />
                    </button>
                  </span>
                ))}
                <input
                  value={targetInput}
                  onChange={(event) => {
                    setTargetInput(event.target.value);
                    setTargetInputError(null);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      handleAddTarget();
                    }
                  }}
                  placeholder="192.168.1.0/24 or 10.0.0.1"
                  disabled={inputsDisabled}
                />
              </div>
              {(targetInputError || targetsError) && (
                <div className="scanner-error">{targetInputError || targetsError}</div>
              )}
            </div>
          </details>

          <details className="scanner-section">
            <summary className="scanner-section-title">
              <ChevronRight size={14} className="scanner-chevron" />
              <span>Ports: {portsSummary}</span>
            </summary>
            <div className="scanner-section-content">
              <select
                className="scanner-select"
                value={draftConfig.port_preset}
                onChange={(event) => handlePresetChange(event.target.value)}
                disabled={inputsDisabled}
              >
                {PORT_PRESETS.map((preset) => (
                  <option key={preset.value} value={preset.value}>
                    {preset.label}
                  </option>
                ))}
              </select>
              {draftConfig.port_preset === "custom" && (
                <>
                  <input
                    className={`scanner-input ${portInputError ? "error" : ""}`}
                    value={portInput}
                    onChange={(event) => {
                      setPortInput(event.target.value);
                      setPortInputError(null);
                    }}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") {
                        event.preventDefault();
                        handleApplyCustomPorts();
                      }
                    }}
                    onBlur={handleApplyCustomPorts}
                    placeholder="22,80,443,8000-9000"
                    disabled={inputsDisabled}
                  />
                  {portInputError && (
                    <div className="scanner-error">{portInputError}</div>
                  )}
                </>
              )}
              {largeScanWarning && <div className="scanner-warning">{largeScanWarning}</div>}
            </div>
          </details>

          <details className="scanner-section">
            <summary className="scanner-section-title">
              <ChevronRight size={14} className="scanner-chevron" />
              <span>Advanced Options</span>
            </summary>
            <div className="scanner-section-content">
              <div className="scanner-slider">
              <div className="scanner-slider-label">
                Ping concurrency <span>{draftConfig.options.ping_concurrency}</span>
              </div>
              <input
                type="range"
                min={32}
                max={512}
                value={draftConfig.options.ping_concurrency}
                onChange={(event) =>
                  setDraftConfig((prev) => ({
                    ...prev,
                    options: { ...prev.options, ping_concurrency: Number(event.target.value) },
                  }))
                }
                disabled={inputsDisabled}
              />
            </div>
            <div className="scanner-slider">
              <div className="scanner-slider-label">
                Port scan workers <span>{draftConfig.options.port_scan_workers}</span>
              </div>
              <input
                type="range"
                min={8}
                max={64}
                value={draftConfig.options.port_scan_workers}
                onChange={(event) =>
                  setDraftConfig((prev) => ({
                    ...prev,
                    options: { ...prev.options, port_scan_workers: Number(event.target.value) },
                  }))
                }
                disabled={inputsDisabled}
              />
            </div>
            <label className="scanner-toggle">
              <input
                type="checkbox"
                checked={draftConfig.options.dns_resolution}
                onChange={(event) =>
                  setDraftConfig((prev) => ({
                    ...prev,
                    options: { ...prev.options, dns_resolution: event.target.checked },
                  }))
                }
                disabled={inputsDisabled}
              />
              DNS resolution
            </label>
            <label className="scanner-toggle">
              <input
                type="checkbox"
                checked={draftConfig.options.aggressive}
                onChange={(event) =>
                  setDraftConfig((prev) => ({
                    ...prev,
                    options: { ...prev.options, aggressive: event.target.checked },
                  }))
                }
                disabled={inputsDisabled}
              />
              OS/Version detection
              </label>
            </div>
          </details>
          </div>

          <div className="scanner-terminal-section">
            <div className="scanner-terminal" ref={terminalRef}>
              {scanOutput.length === 0 ? (
                <div className="scanner-terminal-empty">No scan output yet.</div>
              ) : (
                scanOutput.map((line, idx) => (
                  <div key={idx} className="scanner-terminal-line">{line}</div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
