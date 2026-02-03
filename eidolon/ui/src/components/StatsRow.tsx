import React from "react";
import { Wifi, Globe, Server, Activity, PieChart } from "lucide-react";
import { filterAssetsByNetwork, getAssetStatus, type GraphNode } from "../api";

interface StatsRowProps {
  assets: GraphNode[];
  network: GraphNode | null;
  isLoading?: boolean;
}

export function StatsRow({ assets, network, isLoading = false }: StatsRowProps) {
  const scopedAssets = filterAssetsByNetwork(assets, network);
  const totalAssets = scopedAssets.length;
  const onlineAssets = scopedAssets.filter((asset) => getAssetStatus(asset) === "online").length;
  const saturation = totalAssets ? (onlineAssets / totalAssets) * 100 : 0;
  const publicIp =
    scopedAssets
      .map((asset) => (asset.metadata as Record<string, unknown> | undefined)?.public_ip)
      .find((ip): ip is string => typeof ip === "string") ?? "n/a";
  const networkLabel = network?.cidr ?? "n/a";
  const saturationLabel = totalAssets ? `${saturation.toFixed(1)}%` : "n/a";

  return (
    <div className="stats-grid">
      <div className="stat-card">
        <div className="stat-icon"><Wifi size={20} /></div>
        <div className="stat-label">Network Range</div>
        <div className="stat-value" style={{ color: "var(--accent)" }}>
          {isLoading ? "Loading..." : networkLabel}
        </div>
      </div>
      <div className="stat-card">
        <div className="stat-icon"><Globe size={20} /></div>
        <div className="stat-label">Public IP</div>
        <div className="stat-value">{isLoading ? "Loading..." : publicIp}</div>
      </div>
      <div className="stat-card">
        <div className="stat-icon"><Server size={20} /></div>
        <div className="stat-label">Devices Found</div>
        <div className="stat-value">{isLoading ? "Loading..." : totalAssets}</div>
      </div>
      <div className="stat-card">
        <div className="stat-icon"><Activity size={20} /></div>
        <div className="stat-label">Online</div>
        <div className="stat-value">
          {isLoading ? "..." : onlineAssets}
        </div>
      </div>
      <div className="stat-card">
        <div className="stat-icon"><PieChart size={20} /></div>
        <div className="stat-label">Saturation</div>
        <div className="stat-value">
          {isLoading ? "..." : saturationLabel}
        </div>
        <div className="progress-bar">
          <div className="progress-fill" style={{ width: `${saturation}%` }}></div>
        </div>
      </div>
    </div>
  );
}
