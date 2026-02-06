import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import ForceGraph2D, { type ForceGraphMethods, type NodeObject, type LinkObject } from "react-force-graph-2d";
import {
  RefreshCw,
  Search,
  ZoomIn,
  ZoomOut,
  Maximize2,
  Target,
  X,
  ChevronRight,
  AlertTriangle,
  Wifi,
  Server,
  Network,
  Shield,
  User,
  Info,
} from "lucide-react";
import {
  getGraphOverview,
  type GraphOverviewEdge,
  type GraphOverviewNode,
} from "../api";

interface GraphViewProps {
  showToast: (message: string, type?: "error" | "warning" | "info" | "success") => void;
  refreshTrigger?: number;
}

// Extended node type for force graph
interface GraphNode extends NodeObject {
  id: string;
  node_id: string;
  label: string;
  name: string | null;
  kind: string | null;
  metadata: Record<string, unknown>;
  // Force graph adds these
  x?: number;
  y?: number;
  vx?: number;
  vy?: number;
}

interface GraphLink extends LinkObject {
  source: string | GraphNode;
  target: string | GraphNode;
  type: string;
  confidence: number | null;
}

// Use CSS variables for theme-aware colors
const getThemeColor = (varName: string): string => {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
};

const LABEL_COLORS: Record<string, string> = {
  Asset: "#7fbf9c",
  NetworkContainer: "#6b9bd1",
  Identity: "#d3a86a",
  Policy: "#d07a7a",
  Service: "#a78bfa",
  Vulnerability: "#e07b8f",
};

const LABEL_ICONS: Record<string, React.ElementType> = {
  Asset: Server,
  NetworkContainer: Network,
  Identity: User,
  Policy: Shield,
  Service: Wifi,
  Vulnerability: AlertTriangle,
};

const getNodeColor = (label: string): string => {
  return LABEL_COLORS[label] || getThemeColor("--muted") || "#9aa3b2";
};

const formatLabel = (label: string): string =>
  label.replace(/([a-z])([A-Z])/g, "$1 $2").replace(/_/g, " ");

const formatUptime = (seconds: number): string => {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const mins = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h ${mins}m`;
  return `${mins}m`;
};

const parseSSLCert = (scriptOutput: string): { subject?: string; issuer?: string; validity?: string } | null => {
  try {
    const subjectMatch = scriptOutput.match(/Subject:\s*(.+?)(?:\n|$)/);
    const issuerMatch = scriptOutput.match(/Issuer:\s*(.+?)(?:\n|$)/);
    const validityMatch = scriptOutput.match(/Not valid (?:before|after):\s*(.+?)(?:\n|$)/);
    return {
      subject: subjectMatch?.[1]?.trim(),
      issuer: issuerMatch?.[1]?.trim(),
      validity: validityMatch?.[1]?.trim(),
    };
  } catch {
    return null;
  }
};

const PortsTable: React.FC<{ ports: any[] }> = ({ ports }) => {
  const openPorts = ports.filter((p) => p.state === "open");
  if (openPorts.length === 0) return <div style={{ color: "var(--muted)", fontSize: "12px" }}>No open ports</div>;
  
  return (
    <div style={{ 
      fontSize: "11px", 
      border: "1px solid var(--border)", 
      borderRadius: "4px", 
      overflow: "hidden",
      marginTop: "8px"
    }}>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead style={{ background: "var(--surface)" }}>
          <tr>
            <th style={{ padding: "6px 8px", textAlign: "left", borderBottom: "1px solid var(--border)" }}>Port</th>
            <th style={{ padding: "6px 8px", textAlign: "left", borderBottom: "1px solid var(--border)" }}>Service</th>
            <th style={{ padding: "6px 8px", textAlign: "left", borderBottom: "1px solid var(--border)" }}>Version</th>
          </tr>
        </thead>
        <tbody>
          {openPorts.map((port, idx) => (
            <tr key={idx} style={{ borderBottom: idx < openPorts.length - 1 ? "1px solid var(--border)" : "none" }}>
              <td style={{ padding: "6px 8px", color: "var(--success)" }}>{port.port}</td>
              <td style={{ padding: "6px 8px" }}>{port.service || "unknown"}</td>
              <td style={{ padding: "6px 8px", fontSize: "10px", color: "var(--muted)" }}>
                {port.product ? `${port.product}${port.version ? ` ${port.version}` : ""}` : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

const OSMatchesList: React.FC<{ matches: any[] }> = ({ matches }) => {
  if (matches.length === 0) return null;
  return (
    <div style={{ marginTop: "8px", fontSize: "11px" }}>
      {matches.slice(0, 3).map((match, idx) => (
        <div key={idx} style={{ 
          marginBottom: "6px", 
          padding: "6px 8px", 
          background: "var(--surface)", 
          borderRadius: "4px",
          borderLeft: `3px solid ${parseInt(match.accuracy || "0") > 90 ? "var(--success)" : parseInt(match.accuracy || "0") > 70 ? "var(--warning)" : "var(--muted)"}`
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>{match.name}</span>
            <span style={{ fontSize: "10px", color: "var(--muted)" }}>{match.accuracy}%</span>
          </div>
        </div>
      ))}
      {matches.length > 3 && (
        <div style={{ fontSize: "10px", color: "var(--muted)", marginTop: "4px" }}>
          +{matches.length - 3} more matches
        </div>
      )}
    </div>
  );
};

const CollapsibleSection: React.FC<{ title: string; defaultOpen?: boolean; children: React.ReactNode }> = ({ 
  title, 
  defaultOpen = true, 
  children 
}) => {
  const [isOpen, setIsOpen] = useState(defaultOpen);
  return (
    <div style={{ marginTop: "12px" }}>
      <div 
        onClick={() => setIsOpen(!isOpen)}
        style={{ 
          display: "flex", 
          alignItems: "center", 
          cursor: "pointer", 
          padding: "6px 0",
          fontWeight: 600,
          fontSize: "12px",
          color: "var(--muted)",
          userSelect: "none"
        }}
      >
        <ChevronRight 
          size={14} 
          style={{ 
            transform: isOpen ? "rotate(90deg)" : "rotate(0deg)", 
            transition: "transform 0.2s",
            marginRight: "4px"
          }} 
        />
        {title}
      </div>
      {isOpen && <div style={{ marginTop: "4px" }}>{children}</div>}
    </div>
  );
};

export function GraphView({ showToast, refreshTrigger }: GraphViewProps) {
  const [rawGraph, setRawGraph] = useState<{ nodes: GraphOverviewNode[]; edges: GraphOverviewEdge[] } | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // Filters
  const [search, setSearch] = useState("");
  const [labelFilter, setLabelFilter] = useState<Record<string, boolean>>({});
  const [edgeFilter, setEdgeFilter] = useState<Record<string, boolean>>({});
  
  // Selection & interaction
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<GraphNode | null>(null);
  const [highlightedNodes, setHighlightedNodes] = useState<Set<string>>(new Set());
  const [highlightedLinks, setHighlightedLinks] = useState<Set<string>>(new Set());
  
  // Graph ref
  const graphRef = useRef<ForceGraphMethods<GraphNode, GraphLink>>();
  const containerRef = useRef<HTMLDivElement>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 600 });

  // Load graph data
  const loadGraph = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await getGraphOverview({ node_limit: 500, edge_limit: 1500 });
      setRawGraph(data);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to load graph data";
      setError(message);
      showToast(`Graph error: ${message}`, "error");
    } finally {
      setIsLoading(false);
    }
  }, [showToast]);

  useEffect(() => {
    loadGraph();
  }, [loadGraph]);

  // Reload graph when data refreshes (e.g., after scan completes)
  useEffect(() => {
    if (refreshTrigger && refreshTrigger > 0) {
      loadGraph();
    }
  }, [refreshTrigger, loadGraph]);

  // Handle container resize
  useEffect(() => {
    if (!containerRef.current) return;
    
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect;
        if (width && height) {
          setDimensions({ width, height });
        }
      }
    });
    
    observer.observe(containerRef.current);
    return () => observer.disconnect();
  }, []);

  // Extract unique labels and relationship types
  const labels = useMemo(() => {
    const set = new Set<string>();
    rawGraph?.nodes.forEach((n) => set.add(n.label));
    return Array.from(set).sort();
  }, [rawGraph]);

  const relationshipTypes = useMemo(() => {
    const set = new Set<string>();
    rawGraph?.edges.forEach((e) => set.add(e.type));
    return Array.from(set).sort();
  }, [rawGraph]);

  // Initialize filters when data loads
  useEffect(() => {
    if (!rawGraph) return;
    setLabelFilter((prev) => {
      const next: Record<string, boolean> = {};
      labels.forEach((l) => (next[l] = prev[l] ?? true));
      return next;
    });
    setEdgeFilter((prev) => {
      const next: Record<string, boolean> = {};
      relationshipTypes.forEach((r) => (next[r] = prev[r] ?? true));
      return next;
    });
  }, [rawGraph, labels, relationshipTypes]);

  // Build filtered graph for force layout
  const graphData = useMemo(() => {
    if (!rawGraph) return { nodes: [], links: [] };

    const normalizedSearch = search.trim().toLowerCase();
    
    const filteredNodes: GraphNode[] = rawGraph.nodes
      .filter((n) => {
        if (labelFilter[n.label] === false) return false;
        if (!normalizedSearch) return true;
        const haystack = `${n.name ?? ""} ${n.node_id}`.toLowerCase();
        return haystack.includes(normalizedSearch);
      })
      .map((n) => ({
        id: n.node_id,
        node_id: n.node_id,
        label: n.label,
        name: n.name ?? null,
        kind: n.kind ?? null,
        metadata: n.metadata ?? {},
      }));

    const nodeIds = new Set(filteredNodes.map((n) => n.id));

    const filteredLinks: GraphLink[] = rawGraph.edges
      .filter(
        (e) =>
          edgeFilter[e.type] !== false &&
          nodeIds.has(e.source) &&
          nodeIds.has(e.target)
      )
      .map((e) => ({
        source: e.source,
        target: e.target,
        type: e.type,
        confidence: e.confidence ?? null,
      }));

    return { nodes: filteredNodes, links: filteredLinks };
  }, [rawGraph, search, labelFilter, edgeFilter]);

  // Build adjacency for highlighting
  const adjacency = useMemo(() => {
    const map = new Map<string, Set<string>>();
    graphData.links.forEach((link) => {
      const sourceId = typeof link.source === "string" ? link.source : link.source.id;
      const targetId = typeof link.target === "string" ? link.target : link.target.id;
      if (!map.has(sourceId)) map.set(sourceId, new Set());
      if (!map.has(targetId)) map.set(targetId, new Set());
      map.get(sourceId)!.add(targetId);
      map.get(targetId)!.add(sourceId);
    });
    return map;
  }, [graphData.links]);

  // Highlight neighbors on hover
  useEffect(() => {
    if (!hoveredNode && !selectedNode) {
      setHighlightedNodes(new Set());
      setHighlightedLinks(new Set());
      return;
    }

    const focusNode = hoveredNode || selectedNode;
    if (!focusNode) return;

    const neighbors = adjacency.get(focusNode.id) ?? new Set<string>();
    const nodeSet = new Set([focusNode.id, ...neighbors]);
    
    const linkSet = new Set<string>();
    graphData.links.forEach((link) => {
      const sourceId = typeof link.source === "string" ? link.source : link.source.id;
      const targetId = typeof link.target === "string" ? link.target : link.target.id;
      if (sourceId === focusNode.id || targetId === focusNode.id) {
        linkSet.add(`${sourceId}-${targetId}`);
      }
    });

    setHighlightedNodes(nodeSet);
    setHighlightedLinks(linkSet);
  }, [hoveredNode, selectedNode, adjacency, graphData.links]);

  // Node rendering
  const paintNode = useCallback(
    (node: GraphNode, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const { x, y, label, name, id } = node;
      if (x === undefined || y === undefined) return;

      const isHighlighted = highlightedNodes.has(id);
      const isDimmed = highlightedNodes.size > 0 && !isHighlighted;
      const isSelected = selectedNode?.id === id;

      const baseRadius = 6;
      const radius = isSelected ? baseRadius * 1.5 : baseRadius;
      const color = getNodeColor(label);

      ctx.beginPath();
      ctx.arc(x, y, radius, 0, 2 * Math.PI);
      ctx.fillStyle = isDimmed ? `${color}40` : color;
      ctx.fill();

      // Border for selected node
      if (isSelected) {
        ctx.strokeStyle = getThemeColor("--text") || "#e6edf3";
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Label for selected node or when zoomed in
      if ((isSelected || globalScale > 1.5) && name) {
        ctx.font = `${11 / globalScale}px sans-serif`;
        const textColor = getThemeColor("--text") || "#e6edf3";
        ctx.fillStyle = isDimmed ? `${textColor}40` : textColor;
        ctx.textAlign = "center";
        ctx.fillText(name, x, y + radius + 10 / globalScale);
      }
    },
    [highlightedNodes, selectedNode]
  );

  // Link rendering
  const paintLink = useCallback(
    (link: GraphLink, ctx: CanvasRenderingContext2D, globalScale: number) => {
      const source = link.source as GraphNode;
      const target = link.target as GraphNode;
      if (!source.x || !source.y || !target.x || !target.y) return;

      const linkId = `${source.id}-${target.id}`;
      const isHighlighted = highlightedLinks.has(linkId);
      const isDimmed = highlightedLinks.size > 0 && !isHighlighted;

      ctx.beginPath();
      ctx.moveTo(source.x, source.y);
      ctx.lineTo(target.x, target.y);
      const linkColor = getThemeColor("--muted") || "#9aa3b2";
      ctx.strokeStyle = isDimmed ? `${linkColor}10` : `${linkColor}50`;
      ctx.lineWidth = isDimmed ? 0.5 : 1;
      ctx.stroke();

      // Arrow
      if (isHighlighted || globalScale > 2) {
        const angle = Math.atan2(target.y - source.y, target.x - source.x);
        const arrowLength = 6 / globalScale;
        const endX = target.x - Math.cos(angle) * 8;
        const endY = target.y - Math.sin(angle) * 8;

        ctx.beginPath();
        ctx.moveTo(endX, endY);
        ctx.lineTo(
          endX - arrowLength * Math.cos(angle - Math.PI / 6),
          endY - arrowLength * Math.sin(angle - Math.PI / 6)
        );
        ctx.lineTo(
          endX - arrowLength * Math.cos(angle + Math.PI / 6),
          endY - arrowLength * Math.sin(angle + Math.PI / 6)
        );
        ctx.closePath();
        ctx.fillStyle = `${linkColor}80`;
        ctx.fill();
      }
    },
    [highlightedLinks]
  );

  // Zoom controls
  const handleZoomIn = () => graphRef.current?.zoom(graphRef.current.zoom() * 1.5, 300);
  const handleZoomOut = () => graphRef.current?.zoom(graphRef.current.zoom() / 1.5, 300);
  const handleFitView = () => graphRef.current?.zoomToFit(400, 50);
  const handleCenterOnNode = (node: GraphNode) => {
    graphRef.current?.centerAt(node.x, node.y, 500);
    graphRef.current?.zoom(2.5, 500);
  };

  // Statistics
  const stats = useMemo(() => ({
    nodes: graphData.nodes.length,
    edges: graphData.links.length,
    labels: labels.filter((l) => labelFilter[l] !== false).length,
    relationships: relationshipTypes.filter((r) => edgeFilter[r] !== false).length,
  }), [graphData, labels, labelFilter, relationshipTypes, edgeFilter]);

  const labelCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    graphData.nodes.forEach((n) => {
      counts[n.label] = (counts[n.label] ?? 0) + 1;
    });
    return counts;
  }, [graphData.nodes]);

  const relationshipCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    graphData.links.forEach((l) => {
      counts[l.type] = (counts[l.type] ?? 0) + 1;
    });
    return counts;
  }, [graphData.links]);

  return (
    <div className="graph-view">
      <div className="section-title">Knowledge Graph</div>

      {/* Stats bar */}
      <div className="graph-stats">
        <div className="graph-stat">
          <span className="graph-stat-value">{stats.nodes}</span>
          <span className="graph-stat-label">Nodes</span>
        </div>
        <div className="graph-stat">
          <span className="graph-stat-value">{stats.edges}</span>
          <span className="graph-stat-label">Edges</span>
        </div>
        <div className="graph-stat">
          <span className="graph-stat-value">{stats.labels}</span>
          <span className="graph-stat-label">Types</span>
        </div>
        <div className="graph-stat">
          <span className="graph-stat-value">{stats.relationships}</span>
          <span className="graph-stat-label">Relations</span>
        </div>
      </div>

      {/* Main content */}
      <div className="graph-main">
        {/* Filters bar */}
        <div className="graph-filters">
          <div className="graph-filter-section">
            <label className="graph-search-box">
              <Search size={14} />
              <input
                type="text"
                placeholder="Search nodes..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {search && (
                <button onClick={() => setSearch("")} className="graph-search-clear">
                  <X size={12} />
                </button>
              )}
            </label>
          </div>

          <div className="graph-filter-section">
            <div className="graph-filter-header">Node Types</div>
            <div className="graph-filter-list">
              {labels.map((label) => {
                const Icon = LABEL_ICONS[label] || Server;
                const count = labelCounts[label] ?? 0;
                const isActive = labelFilter[label] !== false;
                return (
                  <button
                    key={label}
                    className={`graph-filter-item ${isActive ? "active" : ""}`}
                    onClick={() =>
                      setLabelFilter((p) => ({ ...p, [label]: !isActive }))
                    }
                  >
                    <span
                      className="graph-filter-dot"
                      style={{ backgroundColor: getNodeColor(label) }}
                    />
                    <Icon size={14} />
                    <span className="graph-filter-name">{formatLabel(label)}</span>
                    <span className="graph-filter-count">{count}</span>
                  </button>
                );
              })}
              {labels.length === 0 && (
                <div className="graph-filter-empty">No node types</div>
              )}
            </div>
          </div>

          <div className="graph-filter-section">
            <div className="graph-filter-header">Relationships</div>
            <div className="graph-filter-list">
              {relationshipTypes.map((rel) => {
                const count = relationshipCounts[rel] ?? 0;
                const isActive = edgeFilter[rel] !== false;
                return (
                  <button
                    key={rel}
                    className={`graph-filter-item ${isActive ? "active" : ""}`}
                    onClick={() =>
                      setEdgeFilter((p) => ({ ...p, [rel]: !isActive }))
                    }
                  >
                    <ChevronRight size={14} />
                    <span className="graph-filter-name">{formatLabel(rel)}</span>
                    <span className="graph-filter-count">{count}</span>
                  </button>
                );
              })}
              {relationshipTypes.length === 0 && (
                <div className="graph-filter-empty">No relationships</div>
              )}
            </div>
          </div>
        </div>

        {/* Graph and details */}
        <div className="graph-content">
          {/* Graph canvas */}
          <div className="graph-canvas-container" ref={containerRef}>
            {isLoading && (
              <div className="graph-overlay">
                <div className="graph-loading">Loading graph...</div>
              </div>
            )}
            {error && (
              <div className="graph-overlay">
                <div className="graph-error">{error}</div>
              </div>
            )}
            {!isLoading && !error && graphData.nodes.length === 0 && (
              <div className="graph-overlay">
                <div className="graph-empty-state">
                  <Network size={48} />
                  <p>No graph data yet</p>
                  <span>Run a network scan to populate the graph</span>
                </div>
              </div>
            )}
          {!isLoading && !error && graphData.nodes.length > 0 && (
            <ForceGraph2D
              ref={graphRef}
              graphData={graphData}
              width={dimensions.width}
              height={dimensions.height}
              nodeCanvasObject={paintNode}
              linkCanvasObject={paintLink}
              onNodeClick={(node) => {
                setSelectedNode(node as GraphNode);
              }}
              onNodeHover={(node) => setHoveredNode(node as GraphNode | null)}
              onBackgroundClick={() => setSelectedNode(null)}
              nodeLabel={(node) => `${(node as GraphNode).name || (node as GraphNode).id}`}
              linkDirectionalArrowLength={0}
              cooldownTicks={100}
              d3AlphaDecay={0.02}
              d3VelocityDecay={0.3}
              enableNodeDrag={true}
              enableZoomInteraction={true}
              enablePanInteraction={true}
            />
          )}

            {/* Zoom controls */}
            <div className="graph-zoom-controls">
              <button onClick={handleZoomIn} title="Zoom in">
                <ZoomIn size={18} />
              </button>
              <button onClick={handleZoomOut} title="Zoom out">
                <ZoomOut size={18} />
              </button>
              <button onClick={handleFitView} title="Fit to view">
                <Maximize2 size={18} />
              </button>
            </div>
          </div>

          {/* Right sidebar - Node details */}
          <div className="graph-details">
            <div className="graph-details-header">
              <Info size={16} />
              <span>Node Details</span>
            </div>
            {!selectedNode && (
              <div className="graph-details-empty">
                <p>Select a node to view details</p>
                <span>Click on any node in the graph</span>
              </div>
            )}
            {selectedNode && (
              <div className="graph-details-content">
                <div className="graph-details-title">
                  <span
                    className="graph-details-dot"
                    style={{ backgroundColor: getNodeColor(selectedNode.label) }}
                  />
                  <span>{selectedNode.name || `Unnamed ${selectedNode.label}`}</span>
                </div>
                
                {/* Basic Info Section */}
                <div className="graph-details-row">
                  <span className="graph-details-label">Type</span>
                  <span className="graph-details-value">
                    {formatLabel(selectedNode.label)}
                  </span>
                </div>
                
                {selectedNode.kind && (
                  <div className="graph-details-row">
                    <span className="graph-details-label">Kind</span>
                    <span className="graph-details-value">{selectedNode.kind}</span>
                  </div>
                )}
                
                <div className="graph-details-row">
                  <span className="graph-details-label">ID</span>
                  <span className="graph-details-value graph-details-id">
                    {selectedNode.id}
                  </span>
                </div>

                <div className="graph-details-row">
                  <span className="graph-details-label">Connections</span>
                  <span className="graph-details-value">
                    {adjacency.get(selectedNode.id)?.size ?? 0} neighbors
                  </span>
                </div>

                {/* Simplified Asset Details */}
                {selectedNode.label === "Asset" && (
                  <>
                    {selectedNode.metadata.hostname && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">Hostname</span>
                        <span className="graph-details-value">{String(selectedNode.metadata.hostname)}</span>
                      </div>
                    )}

                    {selectedNode.metadata.mac_address && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">MAC</span>
                        <span className="graph-details-value" style={{ fontFamily: "monospace", fontSize: "11px" }}>
                          {String(selectedNode.metadata.mac_address)}
                        </span>
                      </div>
                    )}

                    {selectedNode.metadata.vendor && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">Vendor</span>
                        <span className="graph-details-value">{String(selectedNode.metadata.vendor)}</span>
                      </div>
                    )}

                    {selectedNode.metadata.status && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">Status</span>
                        <span className="graph-details-value">
                          <span style={{ 
                            color: selectedNode.metadata.status === "online" ? "var(--success)" : "var(--muted)",
                            display: "inline-flex",
                            alignItems: "center",
                            gap: "4px"
                          }}>
                            <span style={{ 
                              width: "6px", 
                              height: "6px", 
                              borderRadius: "50%", 
                              background: "currentColor" 
                            }} />
                            {String(selectedNode.metadata.status)}
                          </span>
                          {selectedNode.metadata.uptime_seconds && (
                            <span style={{ color: "var(--muted)", marginLeft: "6px" }}>
                              • {formatUptime(Number(selectedNode.metadata.uptime_seconds))}
                            </span>
                          )}
                        </span>
                      </div>
                    )}

                    {selectedNode.metadata.cidr && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">Network</span>
                        <span className="graph-details-value" style={{ fontFamily: "monospace" }}>
                          {String(selectedNode.metadata.cidr)}
                        </span>
                      </div>
                    )}

                    {selectedNode.metadata.os_matches && Array.isArray(selectedNode.metadata.os_matches) && selectedNode.metadata.os_matches.length > 0 && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">OS</span>
                        <span className="graph-details-value">
                          {String((selectedNode.metadata.os_matches[0] as any).name)}
                          {(selectedNode.metadata.os_matches[0] as any).accuracy && (
                            <span style={{ 
                              marginLeft: "6px",
                              color: Number((selectedNode.metadata.os_matches[0] as any).accuracy) >= 90 ? "var(--success)" : "var(--warning)"
                            }}>
                              {String((selectedNode.metadata.os_matches[0] as any).accuracy)}%
                            </span>
                          )}
                        </span>
                      </div>
                    )}

                    {selectedNode.metadata.ports && Array.isArray(selectedNode.metadata.ports) && selectedNode.metadata.ports.length > 0 && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">Ports</span>
                        <span className="graph-details-value" style={{ fontSize: "11px" }}>
                          {(() => {
                            const openPorts = selectedNode.metadata.ports.filter((p: any) => p.state === "open");
                            if (openPorts.length === 0) {
                              return <span style={{ color: "var(--muted)" }}>No open ports</span>;
                            }
                            return (
                              <>
                                {openPorts.slice(0, 5).map((port: any, idx: number) => {
                                  const portNum = String(port.port || "?");
                                  const service = String(port.service || "");
                                  return (
                                    <span key={idx} style={{ color: "var(--success)" }}>
                                      {idx > 0 && ", "}
                                      {portNum}{service && `/${service}`}
                                    </span>
                                  );
                                })}
                                {openPorts.length > 5 && <span style={{ color: "var(--muted)" }}> +{openPorts.length - 5} more</span>}
                              </>
                            );
                          })()}
                        </span>
                      </div>
                    )}

                    {(selectedNode.metadata.distance !== undefined || selectedNode.metadata.rtt_srtt_us) && (
                      <div className="graph-details-row">
                        <span className="graph-details-label">Latency</span>
                        <span className="graph-details-value">
                          {selectedNode.metadata.distance !== undefined && `${String(selectedNode.metadata.distance)} hops`}
                          {selectedNode.metadata.distance !== undefined && selectedNode.metadata.rtt_srtt_us && " • "}
                          {selectedNode.metadata.rtt_srtt_us && `${(Number(selectedNode.metadata.rtt_srtt_us) / 1000).toFixed(2)}ms`}
                        </span>
                      </div>
                    )}
                  </>
                )}

                {/* Network Container specific info */}
                {selectedNode.label === "NetworkContainer" && selectedNode.metadata.cidr && (
                  <div className="graph-details-row">
                    <span className="graph-details-label">CIDR</span>
                    <span className="graph-details-value" style={{ fontFamily: "monospace" }}>
                      {String(selectedNode.metadata.cidr)}
                    </span>
                  </div>
                )}

                <div className="graph-details-actions">
                  <button onClick={() => handleCenterOnNode(selectedNode)}>
                    <Target size={14} /> Center
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
