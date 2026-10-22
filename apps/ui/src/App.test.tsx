import { render, screen } from "@testing-library/react";
import App from "./App";

test("app renders shell", () => {
  render(<App />);
  expect(screen.getByText("AGENT://控制中心")).toBeInTheDocument();
});
