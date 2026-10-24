import { spawn, spawn as spawnCb, ChildProcess } from "child_process";
import net from "net";
import path from "path";

export function buildWorkerCommand(opts: { repoRoot: string; port: number }) {
  return {
    command: "uv",
    args: ["run", "python", "-m", "worker", "serve", "--port", String(opts.port)],
    cwd: path.join(opts.repoRoot, "worker"),
  };
}

export async function findFreePort(): Promise<number> {
  return new Promise((resolve) => {
    const srv = net.createServer();
    srv.listen(0, "127.0.0.1", () => {
      const port = (srv.address() as net.AddressInfo).port;
      srv.close(() => resolve(port));
    });
  });
}

export function spawnWorker(opts: { repoRoot: string; port: number }): ChildProcess {
  const spec = buildWorkerCommand(opts);
  const child = spawn(spec.command, spec.args, { cwd: spec.cwd, windowsHide: true });
  child.stdout!.on("data", (d) => console.log(`[worker] ${d}`));
  child.stderr!.on("data", (d) => console.error(`[worker] ${d}`));
  return child;
}

// Windows 下 child.kill() 只杀 uv 不杀 python 子进程（孤儿 worker 持有 agent.db 与端口），
// 必须用 taskkill /t 整树终止（决策 #28）
export function killTree(child: ChildProcess): void {
  if (child.pid === undefined) return;
  if (process.platform === "win32") {
    spawnCb("taskkill", ["/pid", String(child.pid), "/f", "/t"], { windowsHide: true });
  } else {
    child.kill("SIGTERM");
  }
}
