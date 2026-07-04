import { useState, useEffect } from "react";
import { ViewContext } from "./view-context";

const STORAGE_KEY = "pulse-view-mode";

export function ViewProvider({ children }) {
  const [view, setView] = useState(() => {
    try {
      return localStorage.getItem(STORAGE_KEY) || "engineer";
    } catch {
      return "engineer";
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(STORAGE_KEY, view);
    } catch {
      // localStorage unavailable
    }
  }, [view]);

  return (
    <ViewContext.Provider value={{ view, setView }}>
      {children}
    </ViewContext.Provider>
  );
}
