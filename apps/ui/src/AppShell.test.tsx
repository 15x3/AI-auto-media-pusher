import { render, screen, fireEvent } from "@testing-library/react";
import { vi } from "vitest";
import App from "./App";
import { WorkerProvider } from "./worker/WorkerProvider";

vi.mock("./worker/WorkerProvider", async (importOriginal) => {
  const orig = await importOriginal<any>();
  const fake = {
    adapters: vi.fn().mockResolvedValue([{ platform_id: "demo", display_name: "本地演示平台" }]),
    drafts: vi.fn().mockResolvedValue([]),
    memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 0, l3_posts: 0 }),
    configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
    health: vi.fn().mockResolvedValue({ status: "ok", detail: "" }),
    run: vi.fn(), approve: vi.fn(), reject: vi.fn(), onEvent: vi.fn(),
  };
  return { ...orig, WorkerProvider: ({ children }: any) => <orig.WorkerProvider apiForTest={fake as any}>{children}</orig.WorkerProvider> };
});

test("shell: topbar with clock + page switch to drafts", async () => {
  render(<App />);
  expect(screen.getByText("AGENT://控制中心")).toBeInTheDocument();
  expect(await screen.findByText("热点雷达")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: /待人工确认|\d/ }));   // 草稿箱卡进入
  expect(await screen.findByText("← 返回仪表盘")).toBeInTheDocument();
  fireEvent.click(screen.getByText("← 返回仪表盘"));
  expect(await screen.findByText("热点雷达")).toBeInTheDocument();
});
