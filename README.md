# cooldown-my-mac

[English](./README.en.md) · **中文**

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch dashboard" width="100%">
</p>

<p align="center">
  <b>为重度 Mac 用户打造的运行时散热 / 负载管理工具</b><br>
  盯着 24 小时挂在机器上的一堆 AI CLI（droid · codex · claude · opencode · cursor-agent ...），<br>
  在它们把你的 Mac 烤热之前把闲置会话、孤儿进程、膨胀的 MCP 工具清掉。
</p>

<p align="center">
  <a href="https://pypi.org/project/cooldown-my-mac/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cooldown-my-mac.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-black">
  <img alt="Tests" src="https://img.shields.io/badge/tests-212%20passing-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

## 为什么要有这个工具

Mac 上已经有不少优秀的"静态"工具：
- [Mole](https://github.com/tw93/Mole) — 磁盘清理、一次性优化
- [mactop](https://github.com/context-labs/mactop) / [macmon](https://github.com/vladkens/macmon) / `mo status` — 系统监控仪表盘
- [stats](https://github.com/exelban/stats) — 菜单栏硬件读数

**但它们都不管"运行时的开发负载"**。当你同时挂着：
- 3 个 droid、2 个 claude-code、1 个 codex，每个都拖着一堆 MCP 工具进程
- 5 个被 tmux/cmux 拉起的 `next dev` / `vite` / `uvicorn`
- 10 个 VS Code / Cursor 的语言服务器 helper
- 一堆忘了关的 `mysql` / `postgres` / `redis` / `nanobot`

——这时候你需要的不是又一个 CPU/Memory 条形图，而是**一个能把进程归因到「哪个项目 / 哪个 AI CLI / 哪个启动器」并一键清理闲置会话**的工具。这就是 `cooldown-my-mac` 的定位。

## 核心卖点

| 能力 | 具体做法 |
|------|---------|
| 🎯 **进程归因** | 每个 node / python / ruby 进程都会被归到：`项目 root`（沿 cwd 向上找 `.git` / `package.json` / `pyproject.toml` 等标记）、`拉起者`（tmux / cmux / vscode / claude / droid / codex / launchd）、`语言 & 框架`（next / vite / uvicorn / rails / cargo / ...）。对找不到 cwd 标记的进程还有 6 级 fallback 归因链（npx / vscode 扩展 / app bundle / stale-cwd 字符串解析 / orphan 桶 / background 桶），**保证 Top Projects 面板里不会出现 `(cwd unknown)` 这种模糊桶**。 |
| 🧠 **AI CLI 专属支持** | 原生识别 droid / codex / claude / opencode / cursor-agent / aider / crush / hermes / nanobot / cmux / tmux 等进程家族，按家族聚合显示数量 + 内存 + 最长闲置时间，支持一键批量 kill 某个家族所有闲置会话。 |
| 🔥 **电池 & 温度深度** | Battery 面板解析 `ioreg AppleSmartBattery`：电量 · **电芯温度** · 健康 · 循环次数 · 充放电流量。Thermal 面板读 `pmset -g therm` + SMC，提供 CPU 节流状态、休眠策略检测。 |
| 📊 **按 P/E 核拆分的 CPU** | Apple Silicon 的性能核 / 效能核会分开显示均值 + 最大值——能立刻看出是单核撑满还是全核压力。 |
| 🚦 **内存压力守卫** | 内存压力 `critical` 时可自动 `sudo purge` + reap 闲置 AI CLI + 发 macOS 通知。可跑 watch 模式长时间守护。 |
| 🌙 **休眠策略修复** | 一键恢复 `displaysleep=10` / `disksleep=10` / 取消 sleep 阻止，把 AI CLI 睡前留下的烂摊子扫掉。 |
| 🛡️ **launchd 审计** | 列出所有 LaunchAgent / LaunchDaemon，拒绝禁用任何 Apple 自家的 agent，只让你处理第三方（Dropbox helper、Zoom daemon、Adobe IPC ...）。 |
| ⚙️ **24 小时规则引擎** | `cool daemon install` 把自己做成 LaunchAgent，按 YAML 规则定时检查内存 / AI CLI 闲置 / 磁盘压力，自动清理并写日志。幂等，可反复 install。 |
| 📝 **可审计** | 每一次 kill / suspend / bootout 都写 `~/Library/Logs/cooldown/operations.log`，JSON 行格式。破坏性操作一律要求 `--yes` 或交互确认。所有命令支持 `--dry-run`。 |

## 安装

### 方式 1：pipx（推荐生产使用）

```bash
pipx install cooldown-my-mac
pipx inject cooldown-my-mac textual   # 可选：启用 cool watch 全屏 TUI
```

会注册两个命令：`cool`（短）和 `cooldown`（完整别名）。需要 Python 3.11+（已在 3.13 / 3.14 上测试）。

### 方式 2：从源码跑（推荐本地开发）

```bash
git clone https://github.com/coldxiangyu163/cooldown-my-mac.git
cd cooldown-my-mac
python3 -m venv .venv
.venv/bin/pip install -e ".[watch,dev]"

# 在 shell 里加个 alias，改完代码立刻生效
echo "alias cool='$(pwd)/.venv/bin/cool'" >> ~/.zshrc
source ~/.zshrc
```

## 快速上手

```bash
cool                              # 进入交互式菜单（Mole 风格），19 个选项
cool status                       # 一次性健康快照（一屏输出）
cool watch                        # 全屏实时仪表盘（见上方截图）
cool menu                         # 同 cool（默认行为）
```

推荐先跑一次 `cool status` 看整体情况，再根据提示决定是 `reap` / `pressure` / `services` 哪条线去收拾。

## 命令详解

### 开发栈洞察 `cool dev` / `cool ports`

```bash
# 谁起了这些 node / python 进程？属于哪个项目？
cool dev                          # 按项目分组（默认），显示 RSS / CPU / 闲置 / launcher
cool dev --by launcher            # 按启动器分组：tmux=12 droid=8 vscode=6 cmux=4 launchd=9
cool dev --by lang                # node=34 python=12 ruby=3 go=2
cool dev --by framework           # next=6 uvicorn=3 rails=1 ...
cool dev --stale                  # 只看孤儿（ppid=launchd）+ 项目 mtime 超过 7 天的进程
cool dev --project macool         # 过滤到指定项目
cool dev --lang python            # 只看 python 家族
cool dev --kill                   # 勾选多项交互式 kill
cool dev --json                   # 结构化输出，便于管道处理

# 端口地图：谁在监听 3000？3000 和 3001 被同一个 pid 占了吗？
cool ports                        # 所有监听端口（过滤 Apple 系统），附 pid/项目/launcher
cool ports 5432                   # 5432 被谁占了？
cool ports 4000:5000              # 端口区间
cool ports --conflict             # 同一端口被多个 pid 占用的冲突
cool ports --free 4000:4100       # 查这段区间里还空着哪些端口（用于找下一个 dev server 端口）
cool ports --kill                 # 选端口 → 杀掉占用它的进程
```

### AI CLI / 进程回收 `cool procs` / `cool reap`

```bash
cool procs                        # 列出所有 AI CLI / 终端复用器，交互多选 kill
cool reap                         # 回收所有已闲置 30 分钟以上的 droid / codex / claude / tmux session
cool reap --dry-run               # 预览会杀掉哪些进程（不会真 kill）
cool reap --kind codex --ai-idle 1800       # 只回收 codex 且闲置超过 30 分钟
cool reap --kind tmux --tmux-no-clients     # tmux 没 client 连着的 session 全清
cool reap --kinds droid,claude,codex --yes  # 批量 + 免确认
```

`reap` 的三重安全：① 不会杀自己所在的进程树（`cool` 启动时会抓祖先链全部排除）② 默认 `SIGTERM` 给进程 3 秒退场机会，超时才 `SIGKILL` ③ 每一次行为都写 oplog。

### 内存压力 `cool pressure`

```bash
cool pressure                                         # 一次评估：normal / warn / critical
cool pressure --watch -n 60                           # 每 60 秒一次，持续监控
cool pressure --watch --notify                        # 压力 critical 时发 macOS 通知
cool pressure --auto-reap --auto-purge --yes         # 压力高时自动 reap AI CLI + sudo purge
cool pressure --watch -n 30 --auto-reap --auto-purge --notify --yes   # 组合：24h 守护
```

### 本地服务 / 大胃口 GUI `cool services` / `cool apps`

```bash
cool services                     # 交互开关：mysql / postgres / redis / elasticsearch / nanobot / hermes
cool services stop mysql postgres -y

cool apps list                    # 列出常见大胃口 GUI 的内存占用：wechat / dingtalk / feishu / lark / qq / teams / slack / zoom
cool apps suspend --kind wechat --kind dingtalk -y    # SIGSTOP（不退出但不再吃 CPU）
cool apps resume --kind wechat -y                     # SIGCONT 恢复
```

### 温度 / 休眠 / launchd

```bash
cool thermal                      # 显示温度 / 节流状态 / 风扇 / pmset 策略
cool thermal --restore            # 恢复 displaysleep=10, disksleep=10, 允许睡眠

cool launchd                      # 列出所有用户级 LaunchAgent（按 RSS 排序）
cool launchd --audit --disable    # 交互式 bootout 选择器（拒绝 Apple 自家 agent）
```

### 24/7 后台规则引擎 `cool daemon`

```bash
cool daemon config-init           # 在 ~/.config/cooldown/config.yaml 写默认配置
cool daemon install               # 注册到 ~/Library/LaunchAgents/ai.cooldown.agent.plist
cool daemon status                # 看是否在跑、最近一次 tick、运行日志路径
cool daemon logs                  # tail 日志
cool daemon uninstall             # bootout + 删 plist
```

配置示例（`~/.config/cooldown/config.yaml`）：
```yaml
tick_interval_seconds: 120
rules:
  - name: reap-idle-ai-when-warm
    if:
      mem_pressure: [warn, critical]
      ai_idle_minutes: 30
    do:
      - reap_idle_ai
  - name: purge-on-critical
    if:
      mem_pressure: [critical]
    do:
      - purge_system
      - notify: "Memory critical — purged system caches"
```

## `cool watch` 界面导览

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch layout" width="100%">
</p>

**布局**（4 行 × 2 列，Ports 横跨底部）：

| 位置 | 面板 | 内容 |
|------|------|------|
| 顶部 | 单行 Header | Health · 机型 · 芯片 · P/E 拓扑 · RAM/Disk · macOS · uptime · 电池温度 · 内存压力 · AI CLI 数 · 最近操作 · tick 间隔 |
| 第 1 行 | CPU \| Memory | CPU 拆分 P 核 / E 核（均值 + 最大）· Memory 含 swap / 压力 |
| 第 2 行 | Thermal \| Battery | 温度警告 / 电源模式 / 休眠策略 · 电量 / 温度 / 健康 / 循环 |
| 第 3 行 | AI CLI \| Top Projects | AI CLI 家族聚合 · 按项目归因的 RSS 排行 |
| 底部 | Listening Ports（跨两列）| port · pid · process · project · launcher |

**快捷键**：

| 键 | 作用 |
|----|------|
| `q` | 退出 |
| `r` / `R` | 强制快速 / 慢速刷新 |
| `p` | 暂停/恢复所有 tick |
| `d` | 切换 dry-run（kill 动作只打印不执行）|
| `k` / `K` | `SIGTERM` / `SIGKILL` 选中行 |
| `1` / `2` / `3` | 焦点切到 AI CLI / Top Projects / Ports 表 |
| `+` / `-` | 快 tick 间隔 ±1 秒 |
| `[` / `]` | 慢 tick 间隔 ±5 秒 |
| `Tab` / 方向键 | 表内导航 |

**双档刷新频率**：CPU / Memory / Thermal / Battery / AI CLI 每 3 秒（fast tick），Top Projects / Ports 每 15 秒（slow tick）。每个采集器跑在独立 worker 里，单个失败不影响其他面板。

## 进程归因（为什么 Top Projects 不会显示 `(cwd unknown)`）

这是 `cooldown-my-mac` 最核心的技术特色。很多进程监控工具只能告诉你"有一堆 node 在跑"，但说不出"属于哪个项目 / 由谁启动"。我们的归因链按严格度从高到低排列：

```
┌──────────────────────────────────────────────────────────────────┐
│  每个 node/python/ruby/go/... 进程依次过以下 7 级归因，先到先赢 │
├──────────────────────────────────────────────────────────────────┤
│  1. npx cache / npm exec / 裸 MCP 工具名 → (npx: <pkg>)         │
│     避免 claude / droid 拉起的 MCP 污染项目桶                    │
├──────────────────────────────────────────────────────────────────┤
│  2. find_root(cwd) → 沿 cwd 向上找 .git/package.json 等 15 种    │
│     marker。命中 monorepo 子目录（apps/web, packages/ui）时      │
│     自动跳到 workspace 根。                                       │
├──────────────────────────────────────────────────────────────────┤
│  3. _synthesize_app_project → cmdline 或 cwd 穿过 X.app/ bundle  │
│     → (app: X)，用于归类 Electron helper                         │
├──────────────────────────────────────────────────────────────────┤
│  4. _synthesize_vscode_ext_project → .vscode/extensions/<pub>.   │
│     <name>-<ver> → (vscode: name)                                │
├──────────────────────────────────────────────────────────────────┤
│  5. _synthesize_cmdline_project → 解析 --dir / --cwd / --prefix  │
│     CLI 参数                                                      │
├──────────────────────────────────────────────────────────────────┤
│  6. _synthesize_cwd_project → 即使 cwd 磁盘上已不存在，也能从    │
│     路径字符串推断（~/personal/project/X, ~/work/X, ~/code/X）   │
├──────────────────────────────────────────────────────────────────┤
│  7. _bucket_orphan_project → ppid=1 且 cwd=/ 的系统级孤儿 →      │
│     (orphan)                                                     │
├──────────────────────────────────────────────────────────────────┤
│  兜底 → (background: <argv0>)，按可执行名收容                    │
└──────────────────────────────────────────────────────────────────┘
```

同时对进程拉起者（launcher）沿 ppid 链往上走，能识别 tmux / cmux / vscode / claude / droid / codex / aider / launchd 等 10+ 种会话类型。

## 安全设计

- **每个破坏性操作都有 `--dry-run`**，先看要杀谁再决定。
- **自保护**：`cool reap` / `cool apps` 会把调用 `cool` 的进程树全部排除（通过采集 `_self_pid_chain`），不会自杀。
- **Apple 系统进程豁免**：`cool launchd` 硬编码拒绝禁用任何 `com.apple.*` / `gui/501/com.apple.*` 路径下的 agent。
- **oplog 审计日志**：`~/Library/Logs/cooldown/operations.log`，JSON 每行一条，能回溯所有 kill / suspend / bootout。设 `COOL_NO_OPLOG=1` 关掉。
- **默认 SIGTERM + 3 秒超时 + SIGKILL**，给进程正常退场的机会。
- **幂等的 daemon**：`cool daemon install` 可反复跑不会重复注册。

## 和相似工具对比

| 工具 | 定位 | 和 cooldown-my-mac 的关系 |
|------|------|--------------------------|
| [Mole](https://github.com/tw93/Mole) | 磁盘清理 + 一次性优化 | **互补**。Mole 管磁盘，cooldown 管进程。一起用效果最好。 |
| [mactop](https://github.com/context-labs/mactop) / [macmon](https://github.com/vladkens/macmon) | Apple Silicon 硬件读数（GPU / ANE / 功耗）| **互补**。它们深入硬件，cooldown 深入用户态进程归因。 |
| [stats](https://github.com/exelban/stats) | 菜单栏长期驻留 | **互补**。stats 适合长期观察，cooldown 适合"今天怎么又卡了"时深入排查。 |
| [btop++](https://github.com/aristocratos/btop) / htop | 通用进程监控 | **重叠但定位不同**。btop 是通用工具，cooldown 针对 Mac + AI CLI 场景深度优化。 |
| Activity Monitor | macOS 自带 | **cooldown 是命令行版 + 项目归因 + 批量操作**。 |

## 常见问答

**Q: 会不会杀掉我正在用的 AI CLI 会话？**  
A: 不会。`reap` 默认只动 `idle_seconds >= 1800`（30 分钟无 tty 活动）的进程。自保护链会排除 cool 自身及其所有祖先。不放心先跑 `--dry-run`。

**Q: 为什么要 `sudo purge`？会不会有副作用？**  
A: `purge` 是 macOS 自带命令，清理文件系统的非活跃缓存。唯一"副作用"是接下来几秒文件系统响应慢一点（因为缓存刚清空）。

**Q: Top Projects 里的 `(npx: chrome-devtools-mcp)` 是什么？可以 kill 吗？**  
A: 这是你本地某个 AI CLI（droid / claude / cursor-agent）启动的 MCP 工具，住在 `~/.npm/_npx/` 缓存里。可以安全 kill，AI CLI 下次需要时会自动重新拉起。

**Q: 支持 Intel Mac 吗？**  
A: 支持。P/E 核拓扑会显示成 "NP+0E"（Intel 没有效能核），电池解析也做了 Intel 的 deci-kelvin 温度兼容。但电池 / 温度相关收集器在 Apple Silicon 上数据更丰富。

**Q: 为什么是 pipx 不是 pip？**  
A: pipx 会把 cool 装到独立 venv 并把命令符号链接到 `~/.local/bin/`，避免污染系统 Python。如果你懂 venv 也可以直接 pip。

## 路线图

- [x] `cool status` — 一次性仪表盘（含 Top Projects by RSS）
- [x] `cool watch` — 全屏实时 Textual 仪表盘（P/E 核 + 电池面板 + 4×2 网格）
- [x] `cool dev` — 开发栈清单 + 7 级归因链
- [x] `cool ports` — 监听端口地图 + pid / 项目 / launcher 归因
- [x] `cool procs` — AI CLI 清单 + 交互 kill
- [x] `cool reap` — 闲置会话回收器
- [x] `cool pressure` — 内存压力守卫
- [x] `cool services` — 本地开发服务开关
- [x] `cool apps` — IM / GUI 应用挂起 & 恢复
- [x] `cool thermal` — 温度面板 + 休眠策略恢复
- [x] `cool launchd` — launchd 审计 + 选择性 bootout
- [x] `cool daemon` — 7×24 规则引擎（launchd 托管）
- [ ] Network 面板（上下行速率 sparkline）
- [ ] Disk Trash / 大文件快速定位
- [ ] 规则引擎的 DSL 完善（复合条件、cooldown 周期）
- [ ] 给 `cool dev --kill` 加上按组 kill（整个项目 / 整个 launcher 一键清）

## 贡献

欢迎 Issue 和 PR。本地开发：

```bash
.venv/bin/pip install -e ".[watch,dev]"
.venv/bin/python -m pytest tests/ -q       # 212 passing
.venv/bin/python -m ruff check cooldown tests
```

代码风格：Ruff（lint + format）+ 类型注解。新加的收集器 / UI 建议同时加回归测试。

## 许可证

MIT © coldxiangyu
