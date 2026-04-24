import { useView } from "../contexts/ViewContext";

const VIEWS = [
  { id: "engineer",  label: "Engineer" },
  { id: "executive", label: "Executive" },
  { id: "slo",       label: "SLO" },
];

export default function ViewToggle() {
  const { view, setView } = useView();

  return (
    <div className="flex rounded-md bg-bg-surface text-[11px] overflow-hidden">
      {VIEWS.map(v => (
        <button
          key={v.id}
          onClick={() => setView(v.id)}
          className={`px-2.5 py-1 cursor-pointer transition-colors ${
            view === v.id
              ? "bg-bg-hover text-text-primary"
              : "text-text-muted hover:text-text-secondary"
          }`}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}
