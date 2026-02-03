import React, { useMemo } from "react";
import {
  filterAssetsByNetwork,
  getAssetStatus,
  getNetworkName,
  getNodeId,
  type GraphNode,
} from "../api";

interface NetworkListProps {
  networks: GraphNode[];
  assets: GraphNode[];
  selectedNetworkId: string | null;
  onSelectNetwork: (id: string | null) => void;
  isLoading?: boolean;
}

export function NetworkList({
  networks,
  assets,
  selectedNetworkId,
  onSelectNetwork,
  isLoading = false,
}: NetworkListProps) {
  const stats = useMemo(
    () =>
      networks.map((network, index) => {
        const fallbackId = network.cidr ?? network.name ?? `network-${index}`;
        const id = getNodeId(network) ?? fallbackId;
        const scopedAssets = network.cidr ? filterAssetsByNetwork(assets, network) : [];
        const online = scopedAssets.filter((asset) => getAssetStatus(asset) === "online").length;
        return {
          id,
          network,
          assets: scopedAssets.length,
          online,
        };
      }),
    [networks, assets]
  );

  return (
    <div className="network-list">
      <div className="section-title">Networks</div>
      {isLoading && <div className="text-muted">Loading networks...</div>}
      {!isLoading && stats.length === 0 && (
        <div className="text-muted">No networks discovered yet.</div>
      )}
      {!isLoading && stats.length > 0 && (
        <div className="network-grid">
          {stats.map(({ id, network, assets: assetCount, online }) => {
            const isActive = id === selectedNetworkId;
            return (
              <button
                key={id}
                type="button"
                className={`network-card ${isActive ? "active" : ""}`}
                onClick={() => onSelectNetwork(id)}
              >
                <div className="network-title">{getNetworkName(network)}</div>
                <div className="network-cidr">{network.cidr ?? "unknown"}</div>
                <div className="network-meta">
                  <span>{network.network_type ?? "network"}</span>
                  <span>{assetCount} assets</span>
                  <span>{online} online</span>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
