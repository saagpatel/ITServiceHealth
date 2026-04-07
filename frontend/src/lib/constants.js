export const STATUS_COLORS = {
  operational: "#10B981",
  degraded: "#F59E0B",
  partial_outage: "#F97316",
  major_outage: "#EF4444",
  unknown: "#6B7280",
};

export const STATUS_LABELS = {
  operational: "Operational",
  degraded: "Degraded",
  partial_outage: "Partial Outage",
  major_outage: "Major Outage",
  unknown: "Unknown",
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
  { key: "networking", label: "Network & VPN" },
  { key: "support", label: "Support" },
];

export const SEVERITY_COLORS = {
  critical: "#EF4444",
  high: "#F97316",
  medium: "#F59E0B",
  low: "#6B7280",
};

export const POLL_INTERVAL_MS = 30_000;
export const STALE_WARNING_MS = 90_000;
export const STALE_CRITICAL_MS = 180_000;
