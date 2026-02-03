import React, { useMemo } from "react";
import {
  expandCidr,
  getAssetIp,
  getAssetStatus,
  isIpInCidr,
  type GraphNode,
} from "../api";

interface NetworkMapProps {
  assets: GraphNode[];
  network: GraphNode | null;
  isLoading?: boolean;
}

const STATUS_RANK: Record<string, number> = {
  offline: 0,
  idle: 1,
  online: 2,
};

export function NetworkMap({ assets, network, isLoading = false }: NetworkMapProps) {
  const cidr = network?.cidr;
  const cells = useMemo(() => {
    if (!cidr) {
      return [];
    }
    
    // Build asset lookup by IP
    const assetsByIp = new Map<string, GraphNode>();
    
    for (const asset of assets) {
      const ip = getAssetIp(asset);
      if (!ip || !isIpInCidr(ip, cidr)) {
        continue;
      }
      assetsByIp.set(ip, asset);
    }
    
    if (assetsByIp.size === 0) {
      return [];
    }
    
    // Compact mode: only discovered devices, sorted by IP
    const ipToNum = (ip: string) => 
      ip.split(".").reduce((acc, octet) => acc * 256 + parseInt(octet), 0);
    
    const sortedIps = Array.from(assetsByIp.keys()).sort((a, b) => ipToNum(a) - ipToNum(b));
    
    return sortedIps.map((ip) => {
      const asset = assetsByIp.get(ip)!;
      const status = getAssetStatus(asset);
      return { ip, status, asset };
    });
  }, [assets, cidr]);

  return (
    <>
      <div className="section-title">Network Map</div>
      <div className="map-container">
        {isLoading && <div className="text-muted">Loading network data...</div>}
        {!isLoading && !cidr && (
          <div className="text-muted">No network data yet. Run a scan to populate the map.</div>
        )}
        {!isLoading && cidr && cells.length === 0 && (
          <div className="text-muted">No address range available for {cidr}.</div>
        )}
        {!isLoading && cells.length > 0 && (
          <div className="grid">
            {cells.map((cell) => {
              const metadata = (cell.asset?.metadata ?? {}) as Record<string, unknown>;
              const hostname = metadata.hostname as string | undefined;
              const mac = metadata.mac as string | undefined;
              const vendor = metadata.vendor as string | undefined;
              const ports = metadata.ports as Array<{ port: number; state: string; service?: string }> | undefined;
              const openPorts = ports?.filter((p) => p.state === "open") ?? [];
              
              const tooltipLines = [
                `IP: ${cell.ip}`,
                hostname ? `Hostname: ${hostname}` : null,
                mac ? `MAC: ${mac}` : null,
                vendor ? `Vendor: ${vendor}` : null,
                `Status: ${cell.status}`,
                openPorts.length > 0
                  ? `Open Ports: ${openPorts.map((p) => `${p.port}${p.service ? ` (${p.service})` : ""}`).join(", ")}`
                  : null,
              ].filter(Boolean);
              
              return (
                <div
                  key={cell.ip}
                  className={`grid-cell ${cell.status}`}
                  title={tooltipLines.join("\n")}
                />
              );
            })}
          </div>
        )}
      </div>
    </>
  );
}
