import { render, screen, waitFor } from "@testing-library/react";
import { test, expect, vi } from "vitest";
import { WorkerProvider, useWorker } from "./WorkerProvider";

const fakeApi = {
  adapters: vi.fn().mockResolvedValue([{ platform_id: "demo", display_name: "本地演示平台" }]),
  drafts: vi.fn().mockResolvedValue([]),
  memoryStats: vi.fn().mockResolvedValue({ l2_prefs: 2, l3_posts: 5 }),
  configStatus: vi.fn().mockResolvedValue({ real_llm: false, has_image: false, has_embedding: false }),
  health: vi.fn().mockResolvedValue({ status: "ok", detail: "" }),
  run: vi.fn(),
  approve: vi.fn(),
  reject: vi.fn(),
  onEvent: vi.fn(),
};

function Probe() {
  const { adapters } = useWorker();
  return <span data-testid="probe">{adapters.map((a) => a.platform_id).join(",")}</span>;
}

test("provider loads adapters on mount", async () => {
  render(
    <WorkerProvider apiForTest={fakeApi as any}>
      <Probe />
    </WorkerProvider>,
  );
  await waitFor(() => expect(screen.getByTestId("probe")).toHaveTextContent("demo"));
  expect(fakeApi.adapters).toHaveBeenCalled();
});
