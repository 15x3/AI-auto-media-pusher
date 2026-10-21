"""CLI 入口：无 Electron 独立运行（python -m worker ...）。

有 config.toml → 真实客户端（LLM/Embedding/文生图/浏览器适配器）；
无 → 回退桩与 demo 平台，并打印配置提示。
"""
import argparse
import sys
from pathlib import Path

from .adapters.base import load_adapters
from .config import load_config
from .llm.client import StubEmbedder, StubLLM
from .llm.openai_compat import OpenAIChatClient, OpenAIEmbedder, OpenAIImageClient
from .memory.store import connect
from .pipeline import Pipeline


def _load_config_if_any(config_path: str | None):
    if config_path is not None:
        if not Path(config_path).exists():
            raise FileNotFoundError(
                f"--config 指定的文件不存在: {config_path}（检查路径或省略 --config 以查找工作目录 config.toml）"
            )
        return load_config(config_path)
    if Path("config.toml").exists():  # 缺省查找：不存在时回退桩模式
        return load_config("config.toml")
    return None


def _browser_builder(cfg, headless_override: bool | None = None):
    def builder(cls):
        # 浏览器适配器注入会话参数；非浏览器适配器（如 demo）不接受这些 kwargs，回退无参构造
        if cfg is not None:
            headless = headless_override if headless_override is not None else cfg.headless
            try:
                return cls(headless=headless, profiles_root=cfg.profiles_root)
            except TypeError:
                pass
        return cls()

    return builder


def _pipeline(db: str, config_path: str | None = None) -> Pipeline:
    cfg = _load_config_if_any(config_path)
    registry = load_adapters(builder=_browser_builder(cfg))
    if cfg and cfg.llm:
        llm = OpenAIChatClient(cfg.llm)
        embedder = OpenAIEmbedder(cfg.embedding) if cfg.embedding else StubEmbedder()
        image_client = OpenAIImageClient(cfg.image) if cfg.image else None
    else:
        llm, embedder, image_client = StubLLM(), StubEmbedder(), None

    return Pipeline(
        registry=registry,
        llm=llm,
        embedder=embedder,
        con=connect(db),
        image_client=image_client,
        images_root=cfg.images_root if cfg else Path("data/images"),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="worker", description="AI 社媒自动化 Worker（CLI 模式）")
    parser.add_argument("--db", default="agent.db", help="SQLite 数据库路径")
    parser.add_argument("--config", default=None, help="config.toml 路径（缺省查找工作目录）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("adapters", help="列出已注册适配器")
    login_p = sub.add_parser("login", help="打开浏览器扫码登录平台")
    login_p.add_argument("platform")
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

    if args.cmd == "login":
        cfg = _load_config_if_any(args.config)
        try:
            adapter = load_adapters(
                builder=_browser_builder(cfg, headless_override=False)  # login 需扫码，强制可见浏览器
            ).get(args.platform)
        except KeyError as exc:
            print(f"未知平台: {args.platform}（python -m worker adapters 查看已注册平台）", file=sys.stderr)
            raise SystemExit(1) from exc
        if not hasattr(adapter, "login"):
            print(f"平台 {args.platform} 不需要登录（无 login 方法）")
            return
        try:
            report = adapter.login()
        finally:
            adapter.close()  # 决策 #20：playwright 无 atexit 钩子，必须显式关闭
        print(f"platform={args.platform} status={report.status.value} detail={report.detail}")
        if report.status.value != "ok":
            raise SystemExit(1)
        return

    if args.cmd == "run":
        try:
            pipe = _pipeline(args.db, args.config)
            draft = pipe.run(platform_id=args.platform)
        except KeyError as exc:
            print(f"未知平台: {args.platform}（python -m worker adapters 查看已注册平台）", file=sys.stderr)
            raise SystemExit(1) from exc
        except RuntimeError as exc:  # 决策 #26⑥：AI/网络类失败的友好错误（含构造期 embedding 探测）
            print(f"运行失败: {exc}", file=sys.stderr)
            raise SystemExit(1) from exc
        print(f"draft_id={draft.draft_id} status={draft.status} platform={draft.platform}")
        print(f"title={draft.title}")
        if draft.images and draft.images[0].startswith("cover-stub:"):
            if _load_config_if_any(args.config) is None:
                print("hint=桩模式——复制 config.example.toml 为 config.toml 并填入 key 以启用真实 LLM/文生图")
            else:
                print("hint=未配置 [image] 段，封面为占位符")
    elif args.cmd == "approve":
        pipe = _pipeline(args.db, args.config)
        result = pipe.approve(args.draft_id, edited_title=args.title, edited_body=args.body)
        status = pipe.drafts[args.draft_id].status
        print(f"status={status} success={result.success} url={result.post_url} error={result.error}")
        if not result.success:
            raise SystemExit(1)
    elif args.cmd == "reject":
        pipe = _pipeline(args.db, args.config)
        pipe.reject(args.draft_id, reason=args.reason)
        print("status=rejected")
