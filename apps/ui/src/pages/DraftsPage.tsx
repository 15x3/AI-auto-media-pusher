import { useEffect, useMemo, useState } from "react";
import { useWorker } from "../worker/WorkerProvider";
import { Draft } from "../worker/api";
import "./drafts.css";

const STATUS_LABEL: Record<string, string> = {
  pending_review: "待审", published: "已发布", rejected: "已驳回",
};

export function DraftsPage({ onBack }: { onBack: () => void }) {
  // 决策 #27：消费 Provider 共享运行态——流水线运行期间禁用审核操作（文案不变）
  const { api, running } = useWorker();
  const [drafts, setDrafts] = useState<Draft[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [reason, setReason] = useState("");
  const [flash, setFlash] = useState("");

  useEffect(() => {
    api.drafts().then((ds) => { setDrafts(ds); if (ds[0]) select(ds[0]); }).catch(() => {});
    // 决策 #31：onEvent 返回退订函数，effect 清理时注销
    return api.onEvent((m) => { if (m === "drafts_changed") api.drafts().then(setDrafts).catch(() => {}); });
  }, [api]);

  const select = (d: Draft) => { setSelected(d.draft_id); setTitle(d.title); setBody(d.body); setFlash(""); };
  const current = useMemo(() => drafts.find((d) => d.draft_id === selected), [drafts, selected]);

  const approve = async () => {
    if (!current) return;
    setFlash("发布中…");
    // 只传实际改动的字段——与 Pipeline 的 edited 判定/降权语义对齐（计划末尾注记）
    const editedTitle = title !== current.title ? title : undefined;
    const editedBody = body !== current.body ? body : undefined;
    const r = await api.approve(current.draft_id, editedTitle, editedBody);
    setFlash(r.success ? `已发布：${r.post_url}` : `发布失败：${r.error ?? ""}`);
  };

  const reject = async () => {
    if (!current) return;
    await api.reject(current.draft_id, reason.trim() || "(未填理由)");
    setFlash("已驳回，理由已沉淀到记忆");
  };

  return (
    <div className="drafts">
      <div className="draft-list">
        <button className="btn-no" onClick={onBack}>← 返回仪表盘</button>
        {drafts.map((d) => (
          <div key={d.draft_id} className={`draft-item${d.draft_id === selected ? " sel" : ""}`}
               onClick={() => select(d)}>
            <div>{d.title}</div>
            <small className={`st-${d.status}`}>{STATUS_LABEL[d.status] ?? d.status} · {d.platform}</small>
          </div>
        ))}
      </div>
      {current ? (
        <div className="draft-editor">
          <input data-testid="editor-title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <textarea data-testid="editor-body" value={body} onChange={(e) => setBody(e.target.value)} />
          {current.status === "pending_review" && (
            <>
              <input placeholder="驳回理由（写入 Agent 记忆）" value={reason}
                     onChange={(e) => setReason(e.target.value)} />
              <div className="draft-actions">
                <button className="btn-ok" onClick={approve} disabled={running}>✓ 通过并发布</button>
                <button className="btn-no" onClick={reject} disabled={running}>✗ 驳回</button>
              </div>
            </>
          )}
          {flash && <div style={{ color: "var(--c-primary)" }}>{flash}</div>}
        </div>
      ) : <div className="draft-editor">暂无草稿</div>}
    </div>
  );
}
