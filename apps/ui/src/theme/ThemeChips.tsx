import { THEMES, useTheme } from "./ThemeProvider";

export function ThemeChips() {
  const { theme, setTheme } = useTheme();
  return (
    <div className="theme-chips">
      {THEMES.map((t) => (
        <button key={t.id} className={`chip${theme === t.id ? " on" : ""}`} aria-pressed={theme === t.id}
                onClick={() => setTheme(t.id)}>
          {t.id}
        </button>
      ))}
    </div>
  );
}
