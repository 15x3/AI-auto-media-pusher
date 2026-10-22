import { render, screen, act } from "@testing-library/react";
import { vi, test, expect, afterEach } from "vitest";
import { MiniClock } from "./MiniClock";

afterEach(() => vi.useRealTimers());

test("clock ticks angles and time text each second", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 21, 15, 49, 20)); // 15:49:20
  render(<MiniClock />);
  const orbit = screen.getByRole("img", { name: "当前时间" });

  // 角度期望按计划公式的精确值：(15%12)*30+49*0.5=114.5、49*6+20*0.1=296
  // （计划文档断言 154.5/302 为笔误，以其公式注释与实现为准）
  expect(orbit.style.getPropertyValue("--hour-angle")).toBe("114.5deg"); // (15%12)*30+49*0.5
  expect(orbit.style.getPropertyValue("--minute-angle")).toBe("296deg"); // 49*6+20*0.1
  expect(orbit.style.getPropertyValue("--second-angle")).toBe("120deg"); // 20*6
  expect(orbit.style.getPropertyValue("--day-angle")).toContain("deg");
  expect(screen.getByTestId("clock-time").textContent).toBe("15:49:20");

  act(() => {
    vi.advanceTimersByTime(1000);
  }); // 15:49:21
  expect(orbit.style.getPropertyValue("--second-angle")).toBe("126deg");
  expect(screen.getByTestId("clock-time").textContent).toBe("15:49:21");
});

test("决策 #30：跨分钟回卷——59s→0s 秒角连续累积为 360deg 而非回卷 0deg", () => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date(2026, 9, 21, 15, 49, 59)); // 15:49:59
  render(<MiniClock />);
  const orbit = screen.getByRole("img", { name: "当前时间" });
  expect(orbit.style.getPropertyValue("--second-angle")).toBe("354deg"); // 59*6

  act(() => {
    vi.advanceTimersByTime(1000);
  }); // 15:50:00
  expect(orbit.style.getPropertyValue("--second-angle")).toBe("360deg"); // 0*6 + 1*360
});
