import { render, screen, fireEvent } from "@testing-library/react";
import { ThemeProvider, THEMES, useTheme } from "./ThemeProvider";
import { ThemeChips } from "./ThemeChips";

function Probe() {
  const { theme } = useTheme();
  return <span data-testid="probe">{theme}</span>;
}

test("默认 frost 且切换持久化到 localStorage", () => {
  localStorage.clear();
  render(
    <ThemeProvider>
      <Probe />
      <ThemeChips />
    </ThemeProvider>,
  );
  expect(screen.getByTestId("probe")).toHaveTextContent("frost");
  expect(document.documentElement.dataset.theme).toBe("frost");

  fireEvent.click(screen.getByRole("button", { name: /matrix/ }));
  expect(document.documentElement.dataset.theme).toBe("matrix");
  expect(localStorage.getItem("app-theme")).toBe("matrix");
  expect(THEMES).toHaveLength(6);
  expect(THEMES.map((t) => t.id)).toEqual(["ion", "matrix", "ember", "synth", "frost", "mono"]);
});

test("localStorage 存无效主题名时回退 frost", () => {
  localStorage.setItem("app-theme", "bogus-theme");
  render(
    <ThemeProvider>
      <Probe />
    </ThemeProvider>,
  );
  expect(screen.getByTestId("probe")).toHaveTextContent("frost");
  expect(document.documentElement.dataset.theme).toBe("frost");
});
