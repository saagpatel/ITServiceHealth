import { useEffect } from "react";

/**
 * Keyboard-shortcuts cheatsheet — triggered by `?` from anywhere.
 *
 * Linear-style convention: one screen listing everything, no search.
 * Keeps the footprint tiny so new shortcuts don't become invisible.
 */
export default function ShortcutsOverlay({ onClose }) {
  useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const shortcuts = [
    { keys: ["?"], desc: "Toggle this help overlay" },
    { keys: ["g"], desc: "Toggle the dependency graph" },
    { keys: ["j", "↓"], desc: "Next service tile" },
    { keys: ["k", "↑"], desc: "Previous service tile" },
    { keys: ["←", "→"], desc: "Navigate within the grid" },
    { keys: ["Home"], desc: "Jump to the worst (first) tile" },
    { keys: ["End"], desc: "Jump to the last tile" },
    { keys: ["Enter"], desc: "Open the focused tile's detail panel" },
    { keys: ["Esc"], desc: "Close any open overlay or panel" },
  ];

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="shortcuts-title"
      className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm
                 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-bg-surface border border-border rounded-lg shadow-2xl
                   max-w-md w-full p-6 space-y-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h2
            id="shortcuts-title"
            className="text-sm font-semibold text-text-primary"
          >
            Keyboard shortcuts
          </h2>
          <button
            onClick={onClose}
            className="text-xs text-text-muted hover:text-text-primary"
            aria-label="Close"
          >
            Esc
          </button>
        </div>

        <ul className="space-y-2">
          {shortcuts.map((s) => (
            <li
              key={s.desc}
              className="flex items-center justify-between text-xs"
            >
              <span className="text-text-secondary">{s.desc}</span>
              <span className="flex gap-1">
                {s.keys.map((k) => (
                  <kbd
                    key={k}
                    className="px-1.5 py-0.5 rounded bg-bg-hover border border-border
                               text-[11px] font-mono text-text-primary"
                  >
                    {k}
                  </kbd>
                ))}
              </span>
            </li>
          ))}
        </ul>

        <p className="text-[11px] text-text-muted pt-2 border-t border-border">
          Type any shortcut from anywhere except text inputs.
        </p>
      </div>
    </div>
  );
}
