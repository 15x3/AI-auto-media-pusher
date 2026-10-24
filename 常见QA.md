# 常见 QA（人工链路测试问题记录）

> 记录人工测试中遇到的"看起来不对劲"的现象：判定是否正常、原因、修复方式。
> 新条目追加在文件末尾。

---

## Q1：`uv run python -m worker login xiaohongshu` 扫码时，登录界面一直持续刷新，正常吗？

**不正常（实现缺陷，已修复）。**

- **现象**：打开登录页后，浏览器大约每 3 秒"刷新"一次登录界面，反复闪切。
- **原因**：旧实现的 `login()` 每 3 秒调用一次 `check_health()` 轮询登录态，而
  `check_health` 每次都会**新开一个标签页**加载平台首页、判定后再关闭。登录扫码
  必须用可见浏览器（非无头），新标签页会抢占前台——看到的"刷新"其实是轮询页签
  在反复闪切，登录页本身并没有重载。功能上能等到登录成功，但体验混乱、反复抢焦点，
  对真实站点也是无谓的重复加载。
- **修复**（`worker/adapters/browser.py`）：登录检测改为双信号——
  1. **主信号**：监视登录页自身 URL 是否跳转离开登录环节（扫码成功后平台会自行
     跳转；判定 = 与 `LOGIN_URL` 同域同路径前缀，或路径含 `/login`），事件驱动、
     零额外页签；
  2. **兜底**：每约 15 秒做一次全量 `check_health`（应对个别站点登录后不跳转）；
     URL 跳转发生后再做一次权威确认，确认失败则限频重试。
- **修复后表现**：等待扫码期间浏览器不再闪切；扫码确认后命令正常返回
  `platform=xiaohongshu status=ok`。超时仍为 180 秒。
- **回归测试**：`worker/tests/test_xiaohongshu.py`
  - `test_login_pending_phase_opens_no_polling_tabs`（等待期零轮询页签）
  - `test_login_detects_redirect_after_scan`（跳转即检测成功）
  - `test_login_fallback_full_check_when_page_stays`（不跳转时的兜底路径）

## Q2：点击"立即调研"报错 "It looks like you are using Playwright Sync API inside the asyncio loop"（已修复）

- **原因**（两层叠加，均已最小复现）：
  1. Playwright sync API 在两次调用之间会保持线程的 running-loop 标记，**同一线程
     第二次 `sync_playwright().start()` 必抛此错**。仪表盘挂载时对多平台并发健康检查，
     第一个适配器启动的 Playwright 实例常驻不关闭，线程归还线程池后被第二个适配器
     复用、再次启动实例 → 触发。
  2. service 层此前用共享多线程池，两个真实适配器会**并发**启动浏览器（profile 锁
     冲突、greenlet 跨线程串扰）。
- **修复**：Playwright 实例改为**按线程惰性单例**（同线程所有适配器共用，永不二次
  start）；service 阻塞调用固定到**单线程执行器**串行执行。
- **附带**：「立即调研」原先硬编码取第一个注册适配器（B站字母序排第一，桩模式点
  不到 demo），已改为热点雷达卡片内的平台选择器，默认 demo。

## Q3：登录/调研时浏览器报 "Target page, context or browser has been closed" 或启动失败？

- 常见诱因：**同时开了两个应用实例（或残留的 worker 进程）**——两个进程会抢同一
  个浏览器 profile 目录（`worker/data/profiles/<platform>`），Chromium 的用户数据
  目录不支持多进程同时使用。
- 处理：关闭多余的应用窗口；如异常退出过，检查并结束残留的
  `python -m worker serve` 进程后再重试。原则上同一时间只运行一个应用实例。
