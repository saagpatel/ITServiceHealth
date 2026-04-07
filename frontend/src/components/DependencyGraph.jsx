import { useRef, useCallback, useEffect } from "react";
import ForceGraph2D from "react-force-graph-2d";
import { usePolling } from "../hooks/use-polling";
import { STATUS_COLORS, SEVERITY_COLORS, POLL_INTERVAL_MS } from "../lib/constants";

export default function DependencyGraph({ onSelectService, onClose }) {
  const graphRef = useRef();
  const { data, loading } = usePolling("/api/services/graph", POLL_INTERVAL_MS);

  useEffect(() => {
    const handleEscape = (e) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [onClose]);

  const handleEngineStop = useCallback(() => {
    if (graphRef.current) {
      graphRef.current.zoomToFit(400, 60);
    }
  }, []);

  const nodeCanvasObject = useCallback((node, ctx, globalScale) => {
    const radius = Math.sqrt((node.downstream_count || 0) + 1) * 4;
    const color = STATUS_COLORS[node.status] || STATUS_COLORS.unknown;
    const fontSize = Math.max(10 / globalScale, 3);

    // Node circle
    ctx.beginPath();
    ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
    ctx.fillStyle = color;
    ctx.fill();

    // Glow for non-operational
    if (node.status !== "operational" && node.status !== "unknown") {
      ctx.beginPath();
      ctx.arc(node.x, node.y, radius + 3, 0, 2 * Math.PI);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.globalAlpha = 0.4;
      ctx.stroke();
      ctx.globalAlpha = 1;
    }

    // Label
    ctx.font = `${fontSize}px Inter, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillStyle = "#e2e8f0";
    ctx.fillText(node.name, node.x, node.y + radius + 3);
  }, []);

  const linkColor = useCallback((link) => {
    const color = SEVERITY_COLORS[link.severity] || SEVERITY_COLORS.low;
    return color + "66"; // 40% opacity
  }, []);

  if (loading || !data) {
    return (
      <div className="fixed inset-0 bg-bg-page z-50 flex items-center justify-center">
        <div className="text-text-muted animate-pulse">Loading dependency graph...</div>
      </div>
    );
  }

  return (
    <div className="fixed inset-0 bg-bg-page z-50">
      <div className="absolute top-4 left-6 z-10">
        <h2 className="text-lg font-semibold text-text-primary">Service Dependencies</h2>
        <p className="text-xs text-text-muted">Node size = downstream impact. Click a service for details.</p>
      </div>
      <button
        onClick={onClose}
        className="absolute top-4 right-6 z-10 text-text-muted hover:text-text-primary cursor-pointer"
        aria-label="Close graph"
      >
        <svg className="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>
      <ForceGraph2D
        ref={graphRef}
        graphData={data}
        nodeId="id"
        nodeCanvasObject={nodeCanvasObject}
        nodePointerAreaPaint={(node, color, ctx) => {
          const radius = Math.sqrt((node.downstream_count || 0) + 1) * 4 + 5;
          ctx.beginPath();
          ctx.arc(node.x, node.y, radius, 0, 2 * Math.PI);
          ctx.fillStyle = color;
          ctx.fill();
        }}
        linkColor={linkColor}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={0.8}
        linkWidth={1}
        backgroundColor="#0b1120"
        onNodeClick={(node) => {
          onSelectService(node.id);
          onClose();
        }}
        warmupTicks={100}
        cooldownTicks={200}
        onEngineStop={handleEngineStop}
        d3AlphaDecay={0.05}
        d3VelocityDecay={0.3}
      />
    </div>
  );
}
