import React, { useMemo } from "react";
import { Globe, Terminal } from "lucide-react";
import {
  filterAssetsByNetwork,
  getAssetIp,
  getAssetMac,
  getAssetName,
  getAssetStatus,
  getNodeId,
  type GraphNode,
} from "../api";

interface DeviceListProps {
  assets: GraphNode[];
  network: GraphNode | null;
  isLoading?: boolean;
}

export function DeviceList({ assets, network, isLoading = false }: DeviceListProps) {
  const scopedAssets = useMemo(
    () => filterAssetsByNetwork(assets, network),
    [assets, network]
  );

  return (
    <>
      <div className="section-title">Network Devices</div>
      {isLoading && <div className="text-muted">Loading devices...</div>}
      {!isLoading && scopedAssets.length === 0 && (
        <div className="text-muted">No devices discovered yet.</div>
      )}
      {!isLoading && scopedAssets.length > 0 && (
        <div className="device-grid">
          {scopedAssets.map((asset) => {
            const name = getAssetName(asset);
            const ip = getAssetIp(asset);
            const mac = getAssetMac(asset);
            const status = getAssetStatus(asset);
            const metadata = (asset.metadata ?? {}) as Record<string, unknown>;
            const vendor = metadata.vendor as string | undefined;
            const hostname = metadata.hostname as string | undefined;
            return (
              <div key={getNodeId(asset) ?? ip} className={`device-card ${status}`}>
                <div className="device-ip">{ip ?? mac ?? "unknown"}</div>
                {hostname && hostname !== ip && <div className="device-mac">{hostname}</div>}
                {mac && <div className="device-mac" style={{ fontSize: "10px", opacity: 0.7 }}>{mac}</div>}
                {vendor && <div className="device-mac" style={{ fontSize: "9px", opacity: 0.6 }}>{vendor}</div>}
                <div className="device-icons">
                  <Globe size={12} />
                  <Terminal size={12} />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </>
  );
}
