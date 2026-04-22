export default function ErrorBanner({ polls }) {
  const errors = polls
    .filter((p) => p.error && !p.loading)
    .map((p) => p.label);

  if (errors.length === 0) return null;

  return (
    <div className="rounded-lg bg-status-major/10 border border-status-major/30 px-4 py-3">
      <div className="flex items-center gap-2">
        <svg className="w-4 h-4 text-status-major shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
        </svg>
        <span className="text-xs font-medium text-status-major">
          Connection issue
        </span>
      </div>
      <p className="text-xs text-text-muted mt-1 ml-6">
        Failed to fetch: {errors.join(", ")}. Data shown may be stale.
      </p>
    </div>
  );
}
