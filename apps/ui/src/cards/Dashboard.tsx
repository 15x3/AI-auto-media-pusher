import { useCallback, useEffect, useState } from "react";
import { Card } from "../components/Card";
import { useWorker } from "../worker/WorkerProvider";
import { Draft } from "../worker/api";
import "./dashboard.css";

export function Dashboard({ onOpenDrafts }: { onOpenDrafts: () => void }) {
  const { api, adapters, running, setRunning } = useWorker();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [mem, setMem] = useState({ l2_prefs: 0, l3_posts: 0 });
  const [health, setHealth] = useState<Record<string, { status: string; detail: string }>>({});

  const refresh = useCallback(() => {
    api.drafts().then(setDrafts).catch(() => {});
    api.memoryStats().then(setMem).catch(() => {});
    for (const a of adapters) api.health(a.platform_id)
      .then((r) => setHealth((prev) => ({ ...prev, [a.platform_id]: r }))).catch(() => {});
  }, [api, adapters]);

  useEffect(() => {
    refresh();
    // 决策 #31：onEvent 返回退订函数，effect 清理时注销
    return api.onEvent((method) => {
      if (method === "drafts_changed") refresh();
      // 决策 #27 双保险：流水线阶段事件到达即退出运行态（promise 结算之外的兜底）
      if (method === "stage_changed") setRunning(false);
    });
  }, [refresh, api, setRunning]);

  // 决策 #27：运行期间全局禁用触发类操作，流水线结束（或失败）后恢复
  const startRun = () => {
    if (!adapters[0] || running) return;
    setRunning(true);
    api.run(adapters[0].platform_id).catch(() => {}).finally(() => setRunning(false));
  };

  const pending = drafts.filter((d) => d.status === "pending_review");
  const published = drafts.filter((d) => d.status === "published");
  const latest = drafts[0];

  return (
    <div className="grid">
      <Card title="热点雷达" note={running ? "running" : "idle"}>
        <div className="num">{latest ? latest.title.slice(0, 12) : "—"}</div>
        <div style={{ marginTop: 4 }}>
          {adapters[0] && (
            <button className="pill" onClick={startRun} disabled={running}>
              {running ? "⏳ 运行中…" : "▶ 立即调研"}
            </button>
          )}
        </div>
      </Card>
      <Card title="流水线状态" note={`共 ${drafts.length} 稿`}>
        <div>
          <span className="pill">调研 ✓</span><span className="pill">生成 ✓</span><span className="pill">配图 ✓</span>
          <span className="pill wait">待审 {pending.length} ⏳</span>
          <span className="pill idle">发布 {published.length}</span>
        </div>
      </Card>
      <Card title="草稿箱" note="待人工确认" active={pending.length > 0}>
        <button className="num" style={{ background: "none", border: "none", font: "inherit" }}
                onClick={onOpenDrafts}>{pending.length}</button>
        <div style={{ marginTop: 4, color: "#b8c9da" }}>点击进入审核 →</div>
      </Card>
      <Card title="账号健康">
        {adapters.map((a) => {
          const st = health[a.platform_id]?.status;
          return (
            <div key={a.platform_id}>
              <span className="dot" style={{ background: st === "ok" ? "var(--c-ok)" : "var(--c-warn)",
                boxShadow: `0 0 8px ${st === "ok" ? "var(--c-ok)" : "var(--c-warn)"}` }} /> {a.platform_id}{" "}
              {st ?? "…"}
            </div>
          );
        })}
      </Card>
      <Card title="记忆库">
        <div>L1 运行 · L2 ×{mem.l2_prefs} · <span style={{ color: "var(--c-secondary)" }}>L3 ×{mem.l3_posts}</span></div>
      </Card>
      <Card title="发布历史" note={`已发布 ${published.length}`}>
        <div className="num">{published.length}</div>
        <div style={{ marginTop: 4, color: "#6e768d" }}>{published[0]?.title ?? "暂无"}</div>
      </Card>
    </div>
  );
}
