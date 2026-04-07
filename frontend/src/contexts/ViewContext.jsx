import { createContext, useContext, useState, useEffect } from "react";

const ViewContext = createContext();
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

export function useView() {
  const ctx = useContext(ViewContext);
  if (!ctx) throw new Error("useView must be used inside ViewProvider");
  return ctx;
}
