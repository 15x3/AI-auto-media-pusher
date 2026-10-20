# AI 社交媒体自动化桌面工具 — 技术文档

> 日期：2026-10-20 · 版本：v1.0（设计定稿，用户已批准） · 配套文档：[产品文档](2026-10-20-ai-social-media-agent-tool-product.md)

## 1. 系统架构：Electron 三进程

```
┌─ React UI（Renderer）── 草稿箱/工作台/健康面板；组件级独立测试
├─ Electron Main ──────── 窗口生命周期、IPC 路由、Worker 进程守护；mock Worker 接口测试
└─ Python Worker ──────── Agent 流水线、Playwright、LLM/Embedding 调用；可脱离 Electron 以 CLI 模式跑 pytest
```

- 通信：localhost WebSocket + JSON-RPC，消息携带 correlation id；三层各自 mock 相邻层即可独立测试。
- 取舍：三进程引入 IPC 序列化与进程生命周期管理成本，换取 Python AI 生态、Worker 崩溃不拖垮 UI、每层独立可测。

### 1.1 仓库结构规划

```
├─ apps/
│  ├─ desktop/          # Electron 主进程 + preload（Node/TS）
│  └─ ui/               # React 渲染层（Vite + TS）
├─ worker/              # Python Worker（uv 管理）
│  ├─ agent/            # 流水线编排（调研→生成→配图→待审→发布）
│  ├─ adapters/         # 平台适配器（放即注册）
│  │  ├─ base.py        # PlatformAdapter 抽象 + 注册表
│  │  ├─ xiaohongshu.py
│  │  └─ bilibili_column.py
│  ├── memory/          # L1/L2/L3
│  ├── llm/             # LLM / 文生图 / embedding 客户端
│  └── rpc/             # JSON-RPC 服务端 + CLI 入口（无 Electron 独立运行）
├─ docs/superpowers/    # 规格 + 计划
└─ e2e/                 # 跨进程端到端测试
```

## 2. 平台适配器四方法契约

```python
class PlatformAdapter(ABC):
    platform_id: str          # 元数据：平台标识 / 名称 / 能力声明

    def check_health(self) -> HealthReport          # 登录态、依赖就绪性
    def fetch_trends(self) -> list[Trend]           # 平台热榜/趋势
    def compose_post(self, content) -> PlatformPost # 平台规范适配：字数/标签/图片尺寸
    def execute_publish(self, post) -> PublishResult# Playwright 发布
```

- **自动注册**：Worker 启动时扫描 `adapters/` 目录，凡继承 `PlatformAdapter` 且四方法齐全的子类自动注册，UI 从 Worker 拉取适配器列表渲染。第三方贡献新平台 = 实现四方法 + 放入目录。
- **`PublishResult` 错误分类**：登录失效 / 选择器失效 / 平台拒绝。错误类型决定重试策略——登录失效 → 提示重新扫码；选择器失效 → 标记适配器待维护，不盲目重试。
- **人机边界即契约边界**：人工审核插入点位于 `compose_post` 与 `execute_publish` 之间。
- **首发适配器**：`xiaohongshu`、`bilibili_column`（两个适配器验证契约设计）。

## 3. 三层记忆系统

| 层 | 内容 | 生命周期 |
|---|---|---|
| L1 工作记忆 | 单次流水线运行上下文（当前选题、草稿、召回的参考帖） | 运行结束归档 |
| L2 Agent 记忆 | Agent 配置 + 交互沉淀偏好（如驳回理由形成的风格约束） | 按 Agent 持久化 |
| L3 全局记忆 | 全部历史帖向量库（内容 + 平台 + 是否被人工修改） | 全局持久化，持续累积 |

- **召回时点：写作前**（而非发帖前），历史帖作为 few-shot 样例进入生成 prompt——"内容风格一致性"的实现机制。
- **写回时点**：发布完成后，内容与结果写入 L3。
- **降权规则**：被用户大幅改写的帖子自动降权，不再作为风格样例。
- 落地选型：SQLite + sqlite-vec；embedding 走 API。

## 4. 发布通道与数据边界

- 发布通道：Playwright 驱动真实 Chromium + Cookie 会话，属**非官方通道，不承诺永不失效**；失效影响被适配器层隔离，单平台故障不影响其余链路。
- 风控红线：不自动绕过验证码（触发风控 → 暂停并转人工）；不做多账号矩阵；发布频率可配置限速。
- 数据：全部本地存储（SQLite）；LLM / 文生图 / embedding 均走用户自备 key 的 API；无自建云端。

## 5. UI 技术实现要点

### 5.1 五变量主题系统

配色由 `--c-primary / --c-secondary / --c-accent / --c-ok / --c-warn` 五个 CSS 变量驱动，主题切换 = 覆盖变量组（`[data-theme="frost"]` 等 6 预置）。所有组件（含时钟指针、光晕、卡片描边、数字渐变）只引用变量，不写死颜色；透明度衍生用 `color-mix()`。

### 5.2 动态背景（低运行成本）

- 三团光晕柔边由径向渐变本身实现（不用 blur 滤镜）；漂移只改 `transform`（GPU 合成线程，不触发重排/重绘），周期 26~34s，`will-change: transform`。
- `prefers-reduced-motion` 时自动静止；卡片毛玻璃为静态一次性渲染，不参与动画循环。

### 5.3 字体

- 标题/Logo：思源宋体（Noto Serif SC）SemiBold 网页字体子集（fontmin 子集化，只打包用到字符），`'Noto Serif SC','SimSun',serif` 回退链。
- 数据/日志：Cascadia Code / Consolas 系统等宽。

### 5.4 顶栏迷你轨道时钟

- 结构复刻 orbital-clock：CSS 变量 `--hour-angle / --minute-angle / --second-angle / --day-angle` 驱动三针（`transform: rotate()`）与日进度环（`conic-gradient` + `radial mask`）。
- 每秒一次 JS 更新 4 个角度变量；秒针带 `.12s` transform 过渡。配色：时针=白、分针=`--c-primary`、秒针=`--c-warn`、日环=`--c-secondary`。
- 来源与逆向分析：`C:\Users\LEGION\Nutstore\1\orbital-clock-analysis\`（农历纯函数 `clock_core.js` 备用，完整版时钟卡片启用时接入）。

## 6. 测试策略（对应三进程可测性）

- **Python Worker**：脱离 Electron 以 CLI 模式运行，pytest 覆盖流水线各阶段、记忆读写、适配器契约（四方法齐全性校验 + 用录制页面 fixture 测选择器）。
- **Electron Main**：mock Worker 的 JSON-RPC 接口，测 IPC 路由、进程守护与重连。
- **React UI**：组件测试覆盖草稿箱编辑流、主题切换、健康面板渲染。
- **适配器契约测试**：注册表启动时校验每个适配器四方法与元数据齐全，缺一即拒绝注册并报错。

## 7. 风险与缓解

- 平台改版导致选择器失效：错误分类 + 待维护标记缓解，接受定期维护成本（自用可接受）。
- Cookie 过期频率未知：`check_health` 常驻监测 + 顶栏状态灯提醒重新扫码。
- LLM 生成内容质量：L3 风格召回 + L2 偏好沉淀 + 人工审核三道闸门兜底。
