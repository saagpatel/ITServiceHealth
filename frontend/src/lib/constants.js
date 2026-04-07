export const STATUS_COLORS = {
  operational: "#34d399",
  degraded: "#fbbf24",
  partial_outage: "#fb923c",
  major_outage: "#f87171",
  unknown: "#6b7280",
};

// RGBA tints for tile backgrounds — punched up
export const STATUS_TINTS = {
  operational: "rgba(52, 211, 153, 0.15)",
  degraded: "rgba(251, 191, 36, 0.18)",
  partial_outage: "rgba(251, 146, 60, 0.18)",
  major_outage: "rgba(248, 113, 113, 0.20)",
  unknown: "rgba(107, 114, 128, 0.08)",
};

// Hover tints — noticeably brighter
export const STATUS_TINTS_HOVER = {
  operational: "rgba(52, 211, 153, 0.25)",
  degraded: "rgba(251, 191, 36, 0.30)",
  partial_outage: "rgba(251, 146, 60, 0.30)",
  major_outage: "rgba(248, 113, 113, 0.32)",
  unknown: "rgba(107, 114, 128, 0.15)",
};

export const STATUS_LABELS = {
  operational: "Operational",
  degraded: "Degraded",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  unknown: "Unknown",
};

export const STATUS_ICONS = {
  operational: "✓",
  degraded: "⚠",
  partial_outage: "●",
  major_outage: "✕",
  unknown: "—",
};

export const CATEGORY_ORDER = [
  { key: "identity", label: "Identity & Access" },
  { key: "productivity", label: "Productivity" },
  { key: "collaboration", label: "Collaboration" },
  { key: "engineering", label: "Engineering" },
  { key: "hr", label: "HR & People" },
  { key: "finance", label: "Finance" },
  { key: "sales", label: "Sales & CRM" },
  { key: "marketing", label: "Marketing" },
  { key: "support", label: "Support" },
];

export const SEVERITY_COLORS = {
  critical: "#ef4444",
  high: "#f97316",
  medium: "#f59e0b",
  low: "#6b7280",
};

export const POLL_INTERVAL_MS = 30_000;
export const UPTIME_POLL_INTERVAL_MS = 300_000;
export const STALE_WARNING_MS = 90_000;
export const STALE_CRITICAL_MS = 180_000;
