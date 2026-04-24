import { useExecutiveData } from "../hooks/use-executive-data";

export default function ExecutiveView() {
  const execData = useExecutiveData();
  if (typeof window !== "undefined") {
    // TEMP: removed in Phase 1 once real surfaces render.
    console.log("[ExecutiveView] execData", execData);
  }
  return <p data-testid="exec-shell">exec shell ready</p>;
}
