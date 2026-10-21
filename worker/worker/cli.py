"""CLI 入口：无 Electron 独立运行（python -m worker ...）。"""
import argparse

from .adapters.base import load_adapters
from .llm.client import StubEmbedder, StubLLM
from .memory.store import connect
from .pipeline import Pipeline


def _pipeline(db: str) -> Pipeline:
    return Pipeline(
        registry=load_adapters(),
        llm=StubLLM(),
        embedder=StubEmbedder(),
        con=connect(db),
    )


def _normalize(text: str | None) -> str | None:
    """空串/纯空白视为未提供（None）——避免「幻影编辑」：L3 降权但内容实际未变。"""
    if text is None:
        return None
    return text.strip() or None


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="worker", description="AI 社媒自动化 Worker（CLI 模式）")
    parser.add_argument("--db", default="agent.db", help="SQLite 数据库路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("adapters", help="列出已注册适配器")
    run_p = sub.add_parser("run", help="跑一轮流水线（到待审草稿）")
    run_p.add_argument("platform")
    approve_p = sub.add_parser("approve", help="审核通过并发布")
    approve_p.add_argument("draft_id")
    approve_p.add_argument("--title", help="改写标题（可选）")
    approve_p.add_argument("--body", help="改写正文（可选）")
    reject_p = sub.add_parser("reject", help="驳回草稿")
    reject_p.add_argument("draft_id")
    reject_p.add_argument("reason")

    args = parser.parse_args(argv)
    if args.cmd == "adapters":
        for pid, adapter in load_adapters().all().items():
            print(f"{pid}\t{adapter.display_name}")
        return

    pipe = _pipeline(args.db)
    if args.cmd == "run":
        draft = pipe.run(platform_id=args.platform)
        print(f"draft_id={draft.draft_id} status={draft.status} platform={draft.platform}")
        print(f"title={draft.title}")
    elif args.cmd == "approve":
        result = pipe.approve(
            args.draft_id, edited_title=_normalize(args.title), edited_body=_normalize(args.body)
        )
        status = pipe.drafts[args.draft_id].status
        print(f"status={status} success={result.success} url={result.post_url} error={result.error}")
        if not result.success:
            raise SystemExit(1)
    elif args.cmd == "reject":
        pipe.reject(args.draft_id, reason=args.reason)
        print("status=rejected")
