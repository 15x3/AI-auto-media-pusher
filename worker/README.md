# AI 社媒自动化 Worker

## 快速开始（桩模式，离线可用）

    cd worker && uv sync
    uv run python -m worker run demo        # 跑一轮到待审草稿
    uv run python -m worker approve d1      # 审核通过并"发布"到 demo_published.json

## 启用真实平台与真实 AI

1. `cp config.example.toml config.toml`，填入 OpenAI 兼容 API key（智谱/DeepSeek/OpenAI 均可）
2. `uv run playwright install chromium`（首次）
3. 扫码登录平台（浏览器可见，180 秒超时）：

       uv run python -m worker login xiaohongshu
       uv run python -m worker login bilibili_column

4. 真实流水线：

       uv run python -m worker run xiaohongshu
       uv run python -m worker approve d1

## 说明

- 选择器以 `tests/fixtures/*.html` 为契约；真实页面改版后发布会返回
  `error=selector_broken`，按 `adapters/*.py` 顶部的 SELECTORS 注释校准。
- 全部凭据（config.toml、浏览器 profile、SQLite）仅在本地，不上传。
- 更换 embedding 模型需新建 DB（向量维度随库固定）。
