import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface RightPanelProps {
  isCollapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}

export function RightPanel({ isCollapsed, onToggle, children }: RightPanelProps) {
  return (
    <aside className={`right-panel ${isCollapsed ? 'collapsed' : ''}`}>
      <div className="right-panel-header">
        <button 
          className="toggle-btn"
          onClick={onToggle}
          aria-label={isCollapsed ? "Expand panel" : "Collapse panel"}
        >
          {isCollapsed ? <ChevronLeft size={20} /> : <ChevronRight size={20} />}
        </button>
        {!isCollapsed && <div className="right-panel-title">Scanner</div>}
      </div>
      <div className="right-panel-content">
        {children}
      </div>
    </aside>
  );
}
