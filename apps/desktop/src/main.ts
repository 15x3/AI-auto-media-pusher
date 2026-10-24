import { app, BrowserWindow, ipcMain } from "electron";
import path from "path";
import { WorkerClient } from "./workerClient";
import { findFreePort, spawnWorker, killTree } from "./spawnWorker";

const isDev = !!process.env.VITE_DEV;
let client: WorkerClient | null = null;
let workerProc: ReturnType<typeof spawnWorker> | null = null;

async function boot() {
  // 打包产物未内置 Python worker（asar 无 worker/，决策 #32 遗留）——spawn 必然
  // ENOENT，直接弹提示窗短路，不进入 30 秒注定失败的连接重试
  if (app.isPackaged) {
    const win = new BrowserWindow({ width: 560, height: 320, backgroundColor: "#05070d" });
    await win.loadURL("data:text/html,<div style='background:#05070d;color:#8b949e;font-family:monospace;padding:24px'><h2 style='color:#e6edf3'>AGENT Console</h2><p>打包版暂未内置 Python Worker。</p><p>当前请使用开发模式运行：<code>npm run dev:desktop</code></p></div>");
    return;
  }

  const port = await findFreePort();
  workerProc = spawnWorker({ repoRoot: path.resolve(__dirname, "../../.."), port });
  // 等 worker 就绪（连接重试 30 次 × 1s）
  for (let i = 0; i < 30; i++) {
    try {
      client = new WorkerClient(`ws://127.0.0.1:${port}`);
      await client.connect();
      break;
    } catch {
      await new Promise((r) => setTimeout(r, 1000));
      client = null;
    }
  }
  if (!client) {
    if (workerProc) killTree(workerProc);
    app.exit(1);
    return;
  }

  client.onNotification((method, params) => {
    for (const win of BrowserWindow.getAllWindows()) win.webContents.send("worker-event", method, params);
  });

  ipcMain.handle("rpc", (_e, payload: { method: string; params: Record<string, unknown> }) =>
    client!.request(payload.method, payload.params),
  );

  const win = new BrowserWindow({
    width: 1360, height: 880, backgroundColor: "#05070d",
    webPreferences: { preload: path.join(__dirname, "preload.js") },
  });
  if (isDev) await win.loadURL("http://localhost:5173");
  else {
    // asar 打包下 __dirname/../../ui/dist 不可达，打包产物经 extraResources 把 ui/dist 落到 resources/ui
    const indexPath = app.isPackaged
      ? path.join(process.resourcesPath, "ui", "index.html")
      : path.join(__dirname, "../../ui/dist/index.html");
    await win.loadFile(indexPath);
  }
}

app.whenReady().then(boot);
// 兜底退出清理：window-all-closed 之外的所有退出路径（Cmd+Q / 任务管理器信号等）不留孤儿 worker
app.on("before-quit", () => {
  if (workerProc) killTree(workerProc);
});
app.on("window-all-closed", () => {
  if (workerProc) killTree(workerProc);
  app.quit();
});
