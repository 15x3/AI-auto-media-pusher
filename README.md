# AI-auto-media-pusher

AI 驱动的社交媒体自动化桌面工具：配置 Agent 后自动调研热点、写内容、生成封面，人工审核后发布到小红书 / B站专栏。

## 架构

Electron 三进程（`apps/ui` React 界面 / `apps/desktop` 主进程守护 / `worker` Python Agent 流水线），
详见 `docs/superpowers/specs/`。

## 开发

    npm install
    cd worker && uv sync && cd ..
    npm run dev:ui          # 终端 1：Vite（5173）
    npm run dev:desktop     # 终端 2：Electron（连 Vite + spawn worker）

## 测试

    cd worker && uv run pytest -v        # Python 侧
    npm test                              # UI + 桌面侧（vitest）

## 使用

    cd worker
    cp config.example.toml config.toml    # 填 API key
    uv run python -m worker login xiaohongshu   # 扫码
    npm start                              # 桌面应用：仪表盘 → 草稿箱审核发布
