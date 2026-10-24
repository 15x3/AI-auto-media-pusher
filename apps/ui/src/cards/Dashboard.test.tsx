import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { WorkerProvider } from "../worker/WorkerProvider";
import { Dashboard } from "./Dashboard";

const drafts = [
  { draft_id: "d1", platform: "demo", title: "AI Agent 一周动态", body: "正文", images: [], status: "published", created_at: "2026-10-21 10:00:00" },
  { draft_id: "d2", platform: "demo", title: "第二篇", body: "正文", images: [], status: "pending_review", created_at: "2026-10-21 11:00:00" },
  { draft_id: "d3", platform: "demo", title: "第三篇", body: "正文", images: [], status: "pending_review", created_at: "2026-10-21 12:00:00" },
];

function makeApi() {
  return {
    adapters: vi.fn().mockResolvedValue([{ platform_id: "demo", display_name: "本地演示平台" }]),
    drafts: vi.fn().mockResolvedValue(drafts),
    memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 12, l3_posts: 342 }),
    configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
    health: vi.fn().mockResolvedValue({ status: "ok", detail: "" }),
    run: vi.fn().mockResolvedValue(drafts[0]),
    approve: vi.fn(), reject: vi.fn(),
    // 决策 #31：onEvent 返回退订函数——挂载即触发一次 drafts_changed 刷新注册
    onEvent: vi.fn((cb) => { cb("drafts_changed", {}); return () => {}; }),
  };
}

test("dashboard renders six cards with aggregated data", async () => {
  const api = makeApi();
  render(
    <WorkerProvider apiForTest={api as any}>
      <Dashboard onOpenDrafts={() => {}} />
    </WorkerProvider>,
  );
  expect(await screen.findByText("热点雷达")).toBeInTheDocument();
  expect(screen.getByText("流水线状态")).toBeInTheDocument();
  expect(screen.getByText("草稿箱")).toBeInTheDocument();
  expect(screen.getByText("账号健康")).toBeInTheDocument();
  expect(screen.getByText("记忆库")).toBeInTheDocument();
  expect(screen.getByText("发布历史")).toBeInTheDocument();
  expect(await screen.findByText("2")).toBeInTheDocument();          // 待审数
  expect(api.drafts).toHaveBeenCalled();
  expect(api.memoryStats).toHaveBeenCalled();
  expect(api.health).toHaveBeenCalledWith("demo");
});

test("决策 #27：点击立即调研进入共享运行态（按钮禁用/运行中），api.run 完成后恢复", async () => {
  const api = makeApi();
  let resolveRun!: (v: unknown) => void;
  api.run.mockImplementation(() => new Promise((r) => { resolveRun = r; }));
  render(
    <WorkerProvider apiForTest={api as any}>
      <Dashboard onOpenDrafts={() => {}} />
    </WorkerProvider>,
  );
  const btn = await screen.findByRole("button", { name: /立即调研/ });
  expect(btn).toBeEnabled();

  await act(async () => { fireEvent.click(btn); });
  expect(api.run).toHaveBeenCalledWith("demo");
  const runningBtn = screen.getByRole("button", { name: /运行中/ });
  expect(runningBtn).toBeDisabled();

  await act(async () => { resolveRun(drafts[0]); });
  await waitFor(() => expect(screen.getByRole("button", { name: /立即调研/ })).toBeEnabled());
});

test("规格审查修正：stage_changed 不清除运行态（service 在 run 开始即广播，仅 finally 复位）", async () => {
  const api = makeApi();
  let resolveRun!: (v: unknown) => void;
  api.run.mockImplementation(() => new Promise((r) => { resolveRun = r; }));
  let emit!: (m: string, p?: any) => void;
  api.onEvent = vi.fn((cb: any) => { emit = cb; return () => {}; });
  render(
    <WorkerProvider apiForTest={api as any}>
      <Dashboard onOpenDrafts={() => {}} />
    </WorkerProvider>,
  );
  const btn = await screen.findByRole("button", { name: /立即调研/ });
  await act(async () => { fireEvent.click(btn); });

  // run 仍在进行中，即使收到 stage_changed 广播也必须保持运行态（否则按钮提前恢复）
  act(() => { emit("stage_changed", { stage: "research" }); });
  expect(screen.getByRole("button", { name: /运行中/ })).toBeDisabled();

  await act(async () => { resolveRun(drafts[0]); });
  await waitFor(() => expect(screen.getByRole("button", { name: /立即调研/ })).toBeEnabled());
});

test("T8 审查 Minor #3：run 失败显示错误文案且不再静默", async () => {
  const api = makeApi();
  api.run.mockRejectedValue(new Error("worker 连接失败"));
  render(
    <WorkerProvider apiForTest={api as any}>
      <Dashboard onOpenDrafts={() => {}} />
    </WorkerProvider>,
  );
  const btn = await screen.findByRole("button", { name: /立即调研/ });
  await act(async () => { fireEvent.click(btn); });
  expect(await screen.findByText("worker 连接失败")).toBeInTheDocument();
  // finally 复位运行态，可重试
  await waitFor(() => expect(screen.getByRole("button", { name: /立即调研/ })).toBeEnabled());
});

test("多适配器：平台选择器默认 demo（桩模式冒烟），切换后 run 用所选平台而非 adapters[0]", async () => {
  const api = makeApi();
  api.adapters.mockResolvedValue([
    { platform_id: "bilibili_column", display_name: "B站专栏" },
    { platform_id: "demo", display_name: "本地演示平台" },
    { platform_id: "xiaohongshu", display_name: "小红书" },
  ]);
  render(
    <WorkerProvider apiForTest={api as any}>
      <Dashboard onOpenDrafts={() => {}} />
    </WorkerProvider>,
  );
  const select = await screen.findByRole("combobox");
  // 默认选中 demo，而非注册序第一的 bilibili_column
  expect((select as HTMLSelectElement).value).toBe("demo");

  fireEvent.change(select, { target: { value: "xiaohongshu" } });
  const btn = screen.getByRole("button", { name: /立即调研/ });
  await act(async () => { fireEvent.click(btn); });
  expect(api.run).toHaveBeenCalledWith("xiaohongshu");
});
