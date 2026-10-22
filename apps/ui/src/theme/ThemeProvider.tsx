import { createContext, useContext, useEffect, useState } from "react";

export const THEMES = [
  { id: "ion", label: "ion · 离子" },
  { id: "matrix", label: "matrix · 矩阵" },
  { id: "ember", label: "ember · 熔岩" },
  { id: "synth", label: "synth · 蒸汽波" },
  { id: "frost", label: "frost · 冰川" },
  { id: "mono", label: "mono · 磷光" },
] as const;

export type ThemeId = (typeof THEMES)[number]["id"];

const ThemeCtx = createContext<{ theme: ThemeId; setTheme: (t: ThemeId) => void }>({
  theme: "frost", setTheme: () => {},
});

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setTheme] = useState<ThemeId>(
    () => (localStorage.getItem("app-theme") as ThemeId | null) ?? "frost",
  );
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem("app-theme", theme);
  }, [theme]);
  return <ThemeCtx.Provider value={{ theme, setTheme }}>{children}</ThemeCtx.Provider>;
}

export const useTheme = () => useContext(ThemeCtx);
