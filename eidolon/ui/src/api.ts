export type GraphNode = {
  id?: string;
  node_id?: string;
  label: string;
  identifiers?: string[];
  metadata?: Record<string, unknown>;
  cidr?: string;
  name?: string;
  network_type?: string;
  lifecycle_state?: string;
  kind?: string;
  env?: string;
  criticality?: string;
  owner_team?: string;
};

export type GraphPath = {
  nodes: string[];
  edges: string[];
  cost?: number;
};

export type GraphOverviewNode = {
  node_id: string;
  label: string;
  name?: string | null;
  kind?: string | null;
  metadata?: Record<string, unknown>;
};

export type GraphOverviewEdge = {
  source: string;
  target: string;
  type: string;
  confidence?: number | null;
};

export type GraphOverviewResponse = {
  nodes: GraphOverviewNode[];
  edges: GraphOverviewEdge[];
};

export type GraphQuery = {
  cypher: string;
  parameters: Record<string, unknown>;
};

export type QueryResponse = {
  answer: string;
  paths?: GraphPath[];
  citations?: Record<string, unknown>[];
  graph_query?: GraphQuery;
  records?: Record<string, unknown>[];
};

export type AuditEvent = {
  audit_id?: string;
  id?: string;
  event_type: string;
  details: Record<string, unknown>;
  timestamp: string;
  status: string;
};

export type AuditListResponse = {
  events: AuditEvent[];
  total: number;
  page: number;
  page_size: number;
  has_more: boolean;
};

export type ChatMessage = {
  message_id: string;
  role: "user" | "assistant" | "system" | "tool";
  content: string;
  timestamp: string;
  metadata?: Record<string, unknown>;
};

export type ChatStreamEvent =
  | { type: "message"; message: ChatMessage }
  | { type: "done" };

export type ChatSession = {
  session_id: string;
  user_id?: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  messages: ChatMessage[];
};

export type ChatSessionSummary = {
  session_id: string;
  title?: string | null;
  created_at: string;
  updated_at: string;
  message_count: number;
};

export type BulkDeleteResponse = {
  status: string;
  deleted: number;
};

export type AuditClearResponse = {
  status: string;
  deleted: number;
};

export type GraphClearResponse = {
  status: string;
  nodes_deleted: number;
};

export type SandboxPermissions = {
  allow_shell: boolean;
  allow_network: boolean;
  allow_file_write: boolean;
  allow_unsafe_tools: boolean;
  allowed_tools: string[] | null;
  blocked_tools: string[];
};

export type ThemeSettings = {
  mode: "dark" | "light";
};

export type LLMSettings = {
  model: string;
  api_base?: string | null;
  api_key?: string | null;
  temperature: number;
  max_tokens: number;
  top_p: number;
  frequency_penalty: number;
  presence_penalty: number;
  max_context_tokens: number;
  max_retries: number;
  retry_delay: number;
};

export type AppSettings = {
  theme: ThemeSettings;
  llm: LLMSettings;
};

export type LLMSettingsUpdate = {
  model?: string | null;
  api_base?: string | null;
  api_key?: string | null;
  temperature?: number | null;
  max_tokens?: number | null;
};

export type AppSettingsUpdate = {
  theme?: ThemeSettings;
  llm?: LLMSettingsUpdate;
};

export type PermissionsResponse = {
  sandbox: SandboxPermissions;
};

export type CollectorRunResponse = {
  task_id: string;
  status: string;
};

export type ScannerOptions = {
  ping_concurrency: number;
  port_scan_workers: number;
  dns_resolution: boolean;
  aggressive: boolean;
};

export type ScannerConfig = {
  network_cidrs: string[];
  ports: number[];
  port_preset: string;
  options: ScannerOptions;
};

export type ScanHistoryItem = {
  id: number;
  started_at?: string | null;
  completed_at?: string | null;
  status: string;
  events_collected: number;
  error_message?: string | null;
  config_summary?: string | null;
};

export type ScanHistoryResponse = {
  scans: ScanHistoryItem[];
};

const API_TOKEN = import.meta.env.VITE_API_TOKEN as string | undefined;

const DEFAULT_HEADERS: Record<string, string> = {
  "Content-Type": "application/json",
  "x-user-id": "ui-user",
  "x-roles": "viewer,planner,executor",
  ...(API_TOKEN ? { Authorization: `Bearer ${API_TOKEN}` } : {}),
};

const IP_REGEX = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$/;
const MAC_REGEX = /^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$/;

export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  (import.meta.env.DEV ? "http://localhost:8080" : window.location.origin);

async function fetchJson<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { ...DEFAULT_HEADERS, ...(init.headers || {}) },
  });
  const text = await response.text();
  if (!response.ok) {
    let detail = text;
    try {
      const payload = JSON.parse(text) as { detail?: string };
      if (payload.detail) {
        detail = payload.detail;
      }
    } catch {
      // ignore JSON parse errors
    }
    throw new Error(detail || `Request failed (${response.status})`);
  }
  if (!text) {
    return {} as T;
  }
  return JSON.parse(text) as T;
}

export function listAssets(limit = 200): Promise<GraphNode[]> {
  return fetchJson(`/graph/assets?limit=${limit}`);
}

export function listNetworks(limit = 100): Promise<GraphNode[]> {
  return fetchJson(`/graph/networks?limit=${limit}`);
}

export function getGraphOverview(params?: {
  node_limit?: number;
  edge_limit?: number;
}): Promise<GraphOverviewResponse> {
  const queryParams = new URLSearchParams();
  if (params?.node_limit) queryParams.set("node_limit", params.node_limit.toString());
  if (params?.edge_limit) queryParams.set("edge_limit", params.edge_limit.toString());
  const url = `/graph/overview${queryParams.toString() ? `?${queryParams.toString()}` : ""}`;
  return fetchJson(url);
}

export function listAuditEvents(params?: {
  page?: number;
  page_size?: number;
  event_type?: string;
  start_date?: string;
  end_date?: string;
}): Promise<AuditListResponse> {
  const queryParams = new URLSearchParams();
  if (params?.page) queryParams.set("page", params.page.toString());
  if (params?.page_size) queryParams.set("page_size", params.page_size.toString());
  if (params?.event_type) queryParams.set("event_type", params.event_type);
  if (params?.start_date) queryParams.set("start_date", params.start_date);
  if (params?.end_date) queryParams.set("end_date", params.end_date);
  
  const url = `/audit/${queryParams.toString() ? '?' + queryParams.toString() : ''}`;
  return fetchJson(url);
}

export function clearAuditEvents(): Promise<AuditClearResponse> {
  return fetchJson("/audit/", { method: "DELETE" });
}

export function getSandboxPermissions(): Promise<SandboxPermissions> {
  return fetchJson("/permissions/").then((data: PermissionsResponse) => data.sandbox);
}

export function updateSandboxPermissions(permissions: SandboxPermissions): Promise<SandboxPermissions> {
  return fetchJson("/permissions/", {
    method: "PUT",
    body: JSON.stringify(permissions),
  }).then((data: PermissionsResponse) => data.sandbox);
}

export function getAppSettings(): Promise<AppSettings> {
  return fetchJson("/settings/");
}

export function updateAppSettings(payload: AppSettingsUpdate): Promise<AppSettings> {
  return fetchJson("/settings/", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function runQuery(question: string): Promise<QueryResponse> {
  return fetchJson("/query", {
    method: "POST",
    body: JSON.stringify({ question }),
  });
}

export function startScan(): Promise<CollectorRunResponse> {
  return fetchJson("/collector/scan", { method: "POST" });
}

export function cancelScan(taskId: string): Promise<{ status: string }> {
  return fetchJson("/collector/scan/cancel", {
    method: "POST",
    body: JSON.stringify({ task_id: taskId }),
  });
}

export function getCollectorConfig(): Promise<ScannerConfig> {
  return fetchJson("/collector/config");
}

export function updateCollectorConfig(payload: ScannerConfig): Promise<ScannerConfig> {
  return fetchJson("/collector/config", {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function listScanHistory(limit = 5): Promise<ScanHistoryResponse> {
  return fetchJson(`/collector/scan/history?limit=${limit}`);
}

export function listChatSessions(): Promise<ChatSessionSummary[]> {
  return fetchJson("/chat/sessions");
}

export function deleteAllChatSessions(): Promise<BulkDeleteResponse> {
  return fetchJson("/chat/sessions", { method: "DELETE" });
}

export function createChatSession(title?: string): Promise<ChatSession> {
  return fetchJson("/chat/sessions", {
    method: "POST",
    body: JSON.stringify({ title: title ?? null }),
  });
}

export function getChatSession(sessionId: string): Promise<ChatSession> {
  return fetchJson(`/chat/sessions/${sessionId}`);
}

export function deleteChatSession(sessionId: string): Promise<{ status: string }> {
  return fetchJson(`/chat/sessions/${sessionId}`, { method: "DELETE" });
}

export function resetGraph(): Promise<GraphClearResponse> {
  return fetchJson("/graph/", { method: "DELETE" });
}

export function getGraphPaths(
  sourceId: string,
  targetId: string,
  maxDepth = 4
): Promise<GraphPath[]> {
  const params = new URLSearchParams({
    source_id: sourceId,
    target_id: targetId,
    max_depth: maxDepth.toString(),
  });
  return fetchJson(`/graph/paths?${params.toString()}`);
}

export function appendChatMessage(
  sessionId: string,
  message: { 
    role: "user" | "assistant" | "system"; 
    content: string; 
    metadata?: Record<string, unknown>;
    request_id?: string;
  }
): Promise<ChatSession> {
  return fetchJson(`/chat/sessions/${sessionId}/messages`, {
    method: "POST",
    body: JSON.stringify(message),
  });
}

export async function appendChatMessageStream(
  sessionId: string,
  message: { role: "user" | "assistant" | "system"; content: string; metadata?: Record<string, unknown> },
  onEvent: (event: ChatStreamEvent) => void,
  signal?: AbortSignal,
  requestId?: string
): Promise<void> {
  const payload = requestId ? { ...message, request_id: requestId } : message;
  const response = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages?stream=true`, {
    method: "POST",
    headers: { ...DEFAULT_HEADERS },
    body: JSON.stringify(payload),
    signal,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed (${response.status})`);
  }
  if (!response.body) {
    throw new Error("No response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) {
        continue;
      }
      try {
        const event = JSON.parse(trimmed) as ChatStreamEvent;
        onEvent(event);
        if (event.type === "done") {
          return;
        }
      } catch {
        // Ignore parse errors for partial lines
      }
    }
  }
}

export function cancelChatRequest(
  sessionId: string,
  requestId: string
): Promise<{ status: string }> {
  return fetchJson(`/chat/sessions/${sessionId}/cancel`, {
    method: "POST",
    body: JSON.stringify({ request_id: requestId }),
  });
}

export function isIpv4(value: string): boolean {
  if (!IP_REGEX.test(value)) {
    return false;
  }
  return value.split(".").every((part) => {
    const num = Number(part);
    return Number.isInteger(num) && num >= 0 && num <= 255;
  });
}

export function getAssetIp(asset: GraphNode): string | null {
  const identifiers = asset.identifiers ?? [];
  const fromIdentifiers = identifiers.find((id) => isIpv4(id));
  if (fromIdentifiers) {
    return fromIdentifiers;
  }
  const metadata = (asset.metadata ?? {}) as Record<string, unknown>;
  const candidate =
    (metadata.ip as string | undefined) ??
    (metadata.ip_address as string | undefined) ??
    (metadata.public_ip as string | undefined);
  if (candidate && isIpv4(candidate)) {
    return candidate;
  }
  return null;
}

export function getAssetName(asset: GraphNode): string {
  // Try to get hostname from metadata first
  const metadata = (asset.metadata ?? {}) as Record<string, unknown>;
  const hostname = 
    (metadata.hostname as string | undefined) ??
    (metadata.name as string | undefined) ??
    (metadata.host as string | undefined);
  
  if (hostname && typeof hostname === "string" && hostname.trim()) {
    return hostname.trim();
  }
  
  // Fall back to hostname from identifiers
  const identifiers = asset.identifiers ?? [];
  const hostnameId = identifiers.find((id) => !isIpv4(id) && !MAC_REGEX.test(id));
  if (hostnameId) {
    return hostnameId;
  }
  
  // Fall back to IP address
  const ip = getAssetIp(asset);
  if (ip) {
    return ip;
  }
  
  // Last resort: use node_id
  return getNodeId(asset) ?? "unknown";
}

export function getAssetMac(asset: GraphNode): string | null {
  const identifiers = asset.identifiers ?? [];
  const fromIdentifiers = identifiers.find((id) => MAC_REGEX.test(id));
  if (fromIdentifiers) {
    return fromIdentifiers;
  }
  const metadata = (asset.metadata ?? {}) as Record<string, unknown>;
  const candidate =
    (metadata.mac as string | undefined) ?? (metadata.mac_address as string | undefined);
  if (candidate && MAC_REGEX.test(candidate)) {
    return candidate;
  }
  return null;
}

export function getAssetStatus(asset: GraphNode): "online" | "idle" | "offline" {
  const metadata = (asset.metadata ?? {}) as Record<string, unknown>;
  const rawStatus = String(
    asset.lifecycle_state ?? metadata.status ?? metadata.state ?? ""
  ).toLowerCase();
  if (
    rawStatus.includes("online") ||
    rawStatus.includes("up") ||
    rawStatus.includes("active") ||
    rawStatus.includes("reachable")
  ) {
    return "online";
  }
  if (rawStatus.includes("idle") || rawStatus.includes("warning") || rawStatus.includes("degraded")) {
    return "idle";
  }
  return "offline";
}

export function getNetworkName(network: GraphNode | null): string {
  if (!network) {
    return "unknown";
  }
  
  // Try name property first
  if (network.name && typeof network.name === "string" && network.name.trim()) {
    return network.name.trim();
  }
  
  // Fall back to CIDR
  if (network.cidr && typeof network.cidr === "string") {
    return network.cidr;
  }
  
  // Fall back to network_type
  const metadata = (network.metadata ?? {}) as Record<string, unknown>;
  const networkType = metadata.network_type as string | undefined;
  if (networkType) {
    return `${networkType} network`;
  }
  
  return "Unnamed network";
}

export function filterAssetsByNetwork(
  assets: GraphNode[],
  network: GraphNode | null
): GraphNode[] {
  const cidr = network?.cidr;
  if (!cidr) {
    return assets;
  }
  return assets.filter((asset) => {
    const ip = getAssetIp(asset);
    return ip ? isIpInCidr(ip, cidr) : false;
  });
}

function ipToNumber(ip: string): number | null {
  if (!isIpv4(ip)) {
    return null;
  }
  const [a, b, c, d] = ip.split(".").map((part) => Number(part));
  return (((a << 24) >>> 0) + (b << 16) + (c << 8) + d) >>> 0;
}

function numberToIp(value: number): string {
  return [
    (value >>> 24) & 255,
    (value >>> 16) & 255,
    (value >>> 8) & 255,
    value & 255,
  ].join(".");
}

function parseCidr(cidr: string): { base: number; maskBits: number } | null {
  const parts = cidr.split("/");
  if (parts.length !== 2) {
    return null;
  }
  const base = ipToNumber(parts[0]);
  const maskBits = Number(parts[1]);
  if (base === null || !Number.isInteger(maskBits) || maskBits < 0 || maskBits > 32) {
    return null;
  }
  const mask = maskBits === 0 ? 0 : (~0 << (32 - maskBits)) >>> 0;
  return { base: base & mask, maskBits };
}

export function isIpInCidr(ip: string, cidr: string): boolean {
  const parsed = parseCidr(cidr);
  const ipValue = ipToNumber(ip);
  if (!parsed || ipValue === null) {
    return false;
  }
  const mask = parsed.maskBits === 0 ? 0 : (~0 << (32 - parsed.maskBits)) >>> 0;
  return (ipValue & mask) === parsed.base;
}

export function expandCidr(cidr: string, maxHosts = 256): string[] {
  const parsed = parseCidr(cidr);
  if (!parsed) {
    return [];
  }
  const hostCount = Math.min(2 ** (32 - parsed.maskBits), maxHosts);
  const addresses: string[] = [];
  for (let i = 0; i < hostCount; i += 1) {
    addresses.push(numberToIp((parsed.base + i) >>> 0));
  }
  return addresses;
}

export function getNodeId(node: GraphNode | Record<string, unknown>): string | null {
  if (!node) {
    return null;
  }
  const asGraphNode = node as GraphNode;
  return (asGraphNode.node_id ?? asGraphNode.id ?? null) as string | null;
}
