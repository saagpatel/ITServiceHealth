import { useRegisterSW } from "virtual:pwa-register/react";

export default function ReloadPrompt() {
  const {
    needRefresh: [needRefresh, setNeedRefresh],
    updateServiceWorker,
  } = useRegisterSW({
    onRegisteredSW(_swUrl, registration) {
      if (registration) {
        setInterval(() => {
          registration.update();
        }, 5 * 60 * 1000);
      }
    },
    onRegisterError(error) {
      console.error("SW registration error:", error);
    },
  });

  if (!needRefresh) return null;

  return (
    <div className="fixed bottom-4 right-4 z-50 rounded-lg bg-bg-surface border border-accent/30 shadow-lg px-4 py-3 max-w-sm animate-slide-in">
      <div className="flex items-center gap-3">
        <div className="flex-1">
          <p className="text-sm font-medium text-text-primary">
            New version available
          </p>
          <p className="text-xs text-text-muted mt-0.5">
            Refresh to get the latest updates.
          </p>
        </div>
        <div className="flex gap-2">
          <button
            onClick={() => setNeedRefresh(false)}
            className="text-xs text-text-muted hover:text-text-secondary px-2 py-1 cursor-pointer"
          >
            Later
          </button>
          <button
            onClick={() => updateServiceWorker(true)}
            className="text-xs font-medium text-bg-page bg-accent hover:bg-accent/90 px-3 py-1.5 rounded-md cursor-pointer"
          >
            Refresh
          </button>
        </div>
      </div>
    </div>
  );
}
