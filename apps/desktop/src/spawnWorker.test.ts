import { test, expect, vi, beforeEach, afterEach } from "vitest";
import path from "path";
import { EventEmitter } from "events";
import type { ChildProcess } from "child_process";
import { spawn } from "child_process";
import { buildWorkerCommand, spawnWorker, killTree } from "./spawnWorker";

// 注意：vi.spyOn(cp, "spawn") 拦不住 spawnWorker.ts 的具名导入（vite-node 在导入期绑定），
// 必须用 vi.mock 整体替换 child_process.spawn 才能可靠断言 taskkill 调用
vi.mock("child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("child_process")>();
  return { ...actual, spawn: vi.fn() };
});

const spawnMock = vi.mocked(spawn);

beforeEach(() => {
  spawnMock.mockClear();
});
afterEach(() => {
  vi.restoreAllMocks();
});

test("spawns uv with serve and resolved worker dir", () => {
  const spec = buildWorkerCommand({ repoRoot: "R:/repo", port: 12345 });
  expect(spec.command).toBe("uv");
  expect(spec.args).toEqual([
    "run", "python", "-m", "worker", "serve", "--port", "12345",
  ]);
  expect(spec.cwd).toBe(path.join("R:/repo", "worker"));   // Windows 下为反斜杠，用 path.join 断言
});

test("spawnWorker 给 child 挂 error 处理器——spawn 失败(ENOENT)不致未处理异常崩溃", () => {
  const child = new EventEmitter() as unknown as ChildProcess;
  child.stdout = new EventEmitter();
  child.stderr = new EventEmitter();
  spawnMock.mockReturnValueOnce(child);

  const errSpy = vi.spyOn(console, "error").mockImplementation(() => {});
  spawnWorker({ repoRoot: "R:/repo", port: 12345 });

  // 无 on("error") 处理器时 EventEmitter 会把 error 同步 throw 出来
  expect(() => child.emit("error", new Error("spawn uv ENOENT"))).not.toThrow();
  expect(errSpy).toHaveBeenCalledWith("[worker] 启动失败:", "spawn uv ENOENT");
});

test("killTree 在 win32 下以 taskkill /pid <pid> /f /t 终止进程树", () => {
  vi.spyOn(process, "platform", "get").mockReturnValue("win32");
  const taskkillProc = { on: vi.fn() };
  spawnMock.mockReturnValueOnce(taskkillProc as unknown as ChildProcess);

  killTree({ pid: 4242 } as ChildProcess);

  expect(spawnMock).toHaveBeenCalledWith(
    "taskkill", ["/pid", "4242", "/f", "/t"], { windowsHide: true },
  );
  // taskkill 自身 spawn 失败（PATH 异常等）也不允许未处理 error
  expect(taskkillProc.on).toHaveBeenCalledWith("error", expect.any(Function));
});

test("killTree 在非 win32 平台退回 child.kill(SIGTERM)", () => {
  vi.spyOn(process, "platform", "get").mockReturnValue("linux");
  const kill = vi.fn();

  killTree({ pid: 99, kill } as unknown as ChildProcess);

  expect(kill).toHaveBeenCalledWith("SIGTERM");
  expect(spawnMock).not.toHaveBeenCalled();
});
