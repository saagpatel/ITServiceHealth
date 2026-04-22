import { useView } from "../contexts/ViewContext";

export default function ViewToggle() {
  const { view, setView } = useView();

  return (
    <div className="flex rounded-md bg-bg-surface text-[11px] overflow-hidden">
      <button
        onClick={() => setView("executive")}
        className={`px-2.5 py-1 cursor-pointer transition-colors ${
          view === "executive"
            ? "bg-bg-hover text-text-primary"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        Executive
      </button>
      <button
        onClick={() => setView("engineer")}
        className={`px-2.5 py-1 cursor-pointer transition-colors ${
          view === "engineer"
            ? "bg-bg-hover text-text-primary"
            : "text-text-muted hover:text-text-secondary"
        }`}
      >
        Engineer
      </button>
    </div>
  );
}
