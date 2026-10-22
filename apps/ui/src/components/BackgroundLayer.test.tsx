import { render } from "@testing-library/react";
import { BackgroundLayer } from "./BackgroundLayer";

test("renders three blobs and grid (reduced-motion friendly)", () => {
  const { container } = render(<BackgroundLayer />);
  expect(container.querySelectorAll(".blob")).toHaveLength(3);
  expect(container.querySelector(".grid-overlay")).toBeInTheDocument();
  expect(container.firstChild).toHaveClass("background-layer");
});
