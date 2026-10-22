import { test, expect } from "vitest";
import path from "path";
import { buildWorkerCommand } from "./spawnWorker";

test("spawns uv with serve and resolved worker dir", () => {
  const spec = buildWorkerCommand({ repoRoot: "R:/repo", port: 12345 });
  expect(spec.command).toBe("uv");
  expect(spec.args).toEqual([
    "run", "python", "-m", "worker", "serve", "--port", "12345",
  ]);
  expect(spec.cwd).toBe(path.join("R:/repo", "worker"));   // Windows 下为反斜杠，用 path.join 断言
});
