# cooldown-my-mac

[English](./README.en.md) · **中文**

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch dashboard" width="100%">
</p>

<p align="center">
  <b>为重度 Mac 用户打造的运行时散热 / 负载管理工具</b><br>
  把 24 小时挂在机器上的 AI CLI（droid · codex · claude · cursor-agent ...）<br>
  在烤热你的 Mac 之前清理掉。
</p>

<p align="center">
  <a href="https://pypi.org/project/cooldown-my-mac/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cooldown-my-mac.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-black">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

[为什么需要它](#为什么需要它) ·
[核心能力](#核心能力) ·
[安装](#安装) ·
[快速上手](#快速上手) ·
[命令一览](#命令一览) ·
[`cool watch` 导览](#cool-watch-界面导览) ·
[进程归因](#进程归因) ·
[安全模型](#安全模型) ·
[与其他工具的关系](#与其他工具的关系) ·
[FAQ](#常见问答) ·
[路线图](#路线图)

## 为什么需要它

Mac 上已经有 [Mole](https://github.com/tw93/Mole)（磁盘清理）、[mactop](https://github.com/context-labs/mactop) / [macmon](https://github.com/vladkens/macmon)（硬件读数）、[stats](https://github.com/exelban/stats)（菜单栏）—— 但**它们都不管你的开发工作负载**。当你同时挂着 3 个 droid + 2 个 claude-code + 5 个 `next dev` + 10 个 IDE 语言服务器 + 一堆忘了关的 mysql/postgres 时，你需要的不是又一个 CPU 条形图，而是**能把进程归因到「项目 / AI CLI / 启动器」并一键清理闲置会话**的工具。

## 核心能力

| | 能力 | 一句话 |
|---|---|---|
| 🎯 | **进程归因** | 每个 dev 进程归到「项目根 + 启动器 + 语言/框架」，7 级 fallback 链兜底 |
| 🧠 | **AI CLI 家族识别** | droid · codex · claude · opencode · cursor-agent · aider · hermes · ... 聚合显示并整族 reap |
| 🔥 | **电池 + SMC 温度** | ioreg 解析电芯温度 / 循环 / 健康；SMC 读 CPU/GPU 温度；CPU 节流状态 |
| 📊 | **P/E 核分开统计** | Apple Silicon 性能核 / 效能核分别给均值 + 最大值 |
| 🚦 | **内存压力守卫** | critical 时自动 `sudo purge` + reap + macOS 通知，可常驻 watch 模式 |
| 🌙 | **休眠策略修复** | 一键恢复 displaysleep / disksleep / 取消 sleep 阻止 |
| 🛡️ | **launchd 审计** | 列第三方 LaunchAgent，硬禁动任何 `com.apple.*` |
| ⚙️ | **24/7 规则引擎** | YAML 规则 + launchd 托管，幂等安装 |
| 📝 | **可审计** | JSONL oplog、`--dry-run`、自保护、SIGTERM + 3s + SIGKILL |
| 🔌 | **脚本友好** | `status / procs / dev / ports / thermal` 全部支持 `--json`，可接 `jq` 流水线 |

## 安装

```bash
pipx install cooldown-my-mac
pipx inject cooldown-my-mac textual   # 可选：启用 cool watch 全屏 TUI
```

需要 Python 3.11+（在 3.13 / 3.14 上测试）。注册两个命令：`cool`（短）和 `cooldown`（完整别名）。

<details>
<summary>从源码安装（本地开发用）</summary>

```bash
git clone https://github.com/coldxiangyu163/cooldown-my-mac.git
cd cooldown-my-mac
python3 -m venv .venv
.venv/bin/pip install -e ".[watch,dev]"
echo "alias cool='$(pwd)/.venv/bin/cool'" >> ~/.zshrc && source ~/.zshrc
```

</details>

## 快速上手

```bash
cool                              # 交互式菜单（Mole 风格）
cool status                       # 一次性健康快照
cool watch                        # 全屏实时仪表盘（见顶部截图）
```

按使用场景找命令：

| 你想... | 跑 |
|---|---|
| 看 Mac 整体健康 | `cool status` |
| 找出最吃资源的 AI CLI 会话 | `cool procs` |
| 一次清掉所有闲置 30 分钟以上的 AI CLI | `cool reap` |
| 看每个 dev 进程属于哪个项目 / 哪个 launcher 拉起 | `cool dev` |
| 查谁占着 5432 端口 | `cool ports 5432` |
| 内存压力高时自动清理 | `cool pressure --watch --auto-reap --auto-purge --yes` |
| 24/7 后台守护 | `cool daemon install` |
| 输出 JSON 喂给脚本 | `cool status --json \| jq` |

举个例子 —— 一台日常挂着几个 AI CLI 的 Mac 上跑 `cool dev` 看到的真实输出：

```text
PROJECT                                 #      RSS  LANGS     LAUNCHERS
────────────────────────────────────────────────────────────────────────────────
(npx: chrome-devtools-mcp)            102    4.1GB  node      claude,codex,droid
search-boss                            31    1.5GB  node      cmux,codex,launchd,vscode
(app: Visual Studio Code)              16    1.3GB  node      vscode
(npx: @modelcontextprotocol/serve...   31    1.2GB  node      claude,codex,droid
(npx: mcp-server-sequential-think...   31    925MB  node      claude,codex,droid
music-train-ios                        14    679MB  node      codex,launchd
```

一眼能看出：3 个 AI CLI（claude / codex / droid）各自启动了 chrome-devtools-mcp，加起来 102 个 node 进程吃 4.1GB；`search-boss` 这个真实项目被 cmux / codex / launchd / vscode 4 个不同 launcher 共同持有。要清理哪一块、留下哪一块，一目了然。

## 命令一览

### 开发栈洞察 — `cool dev` · `cool ports`

```bash
cool dev                          # 按项目分组（默认），显示 RSS / CPU / 闲置 / launcher
cool dev --by launcher            # 按启动器分组：tmux=12 droid=8 vscode=6 ...
cool dev --stale                  # 只看孤儿 + 项目 mtime 超过 7 天的进程
cool dev --kill                   # 多选交互式 kill

cool ports                        # 所有监听端口，附 pid / 项目 / launcher
cool ports 5432                   # 5432 被谁占了？
cool ports --free 4000:4100       # 这段区间里还空着哪些端口
```

<details>
<summary>更多 flag（按 lang / framework 分组、按项目过滤、端口冲突...）</summary>

```bash
cool dev --by lang                # node=34 python=12 ruby=3 go=2
cool dev --by framework           # next=6 uvicorn=3 rails=1 ...
cool dev --project macool         # 过滤到指定项目
cool dev --lang python            # 只看 python 家族
cool dev --json                   # 结构化输出，便于管道处理

cool ports 4000:5000              # 端口区间
cool ports --conflict             # 同一端口被多个 pid 占用的冲突
cool ports --kill                 # 选端口 → 杀掉占用它的进程
```

</details>

### 进程回收 — `cool procs` · `cool reap`

```bash
cool procs                        # 列出所有 AI CLI / 终端复用器，多选 kill
cool reap                         # 回收所有闲置 ≥30 分钟的 AI CLI / tmux session
cool reap --dry-run               # 预览要杀的进程（不真 kill）
cool reap --kinds droid,claude --yes        # 限定家族 + 免确认
```

三重安全：① 不杀自己所在的进程树 ② SIGTERM + 3s 宽限 + SIGKILL ③ 全部行为写 [oplog](#安全模型)。

### 内存压力 — `cool pressure`

```bash
cool pressure                                         # 一次评估：normal / warn / critical
cool pressure --watch -n 60                           # 每 60 秒一次，持续监控
cool pressure --watch --auto-reap --auto-purge --notify --yes   # 24h 守护组合
```

### 服务 & 应用 — `cool services` · `cool apps`

```bash
cool services                     # 交互开关：mysql / postgres / redis / elasticsearch / nanobot / hermes
cool services stop mysql postgres -y

cool apps list                    # 列出常见大胃口 GUI 的内存占用：wechat / dingtalk / feishu / lark / qq / teams / slack / zoom
cool apps suspend --kind wechat --kind dingtalk -y    # SIGSTOP（不退出但不再吃 CPU）
cool apps resume --kind wechat -y                     # SIGCONT 恢复
```

### 温度 & launchd — `cool thermal` · `cool launchd`

```bash
cool thermal                      # 显示温度 / 节流状态 / 风扇 / pmset 策略
cool thermal --restore            # 恢复 displaysleep=10, disksleep=10, 允许睡眠

cool launchd                      # 列出所有用户级 LaunchAgent（按 RSS 排序）
cool launchd --audit --disable    # 交互式 bootout 选择器（拒绝 Apple 自家 agent）
```

### 后台守护 — `cool daemon`

```bash
cool daemon config-init           # 写默认 ~/.config/cooldown/config.yaml
cool daemon install               # 注册到 ~/Library/LaunchAgents/
cool daemon status                # 运行状态 + 日志路径
cool daemon logs                  # tail 日志
cool daemon uninstall             # bootout + 删 plist
```

<details>
<summary>YAML 规则配置示例</summary>

`~/.config/cooldown/config.yaml`：

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

</details>

## `cool watch` 界面导览

布局 4 行 × 2 列，Ports 横跨底部（[顶部](#cooldown-my-mac)有截图）：

```text
┌─ Health · 机型 · 芯片 · RAM/Disk · macOS · uptime · 电池温度 · 内存压力 · ⟳ 3s/15s ─┐
├──────────────────────────────────┬──────────────────────────────────┤
│  CPU                             │  Memory                          │  fast (3s)
│  P 核 / E 核 均值 + 最大          │  used / avail · swap · pressure  │
├──────────────────────────────────┼──────────────────────────────────┤
│  Thermal                         │  Battery                         │  fast (3s)
│  warning · throttle · 风扇        │  % · 温度 · 循环 · 健康           │
├──────────────────────────────────┼──────────────────────────────────┤
│  AI CLI Inventory                │  Top Projects by RSS             │  slow (15s)
│  kind · count · rss · idle       │  project · # · rss · launchers   │
├──────────────────────────────────┴──────────────────────────────────┤
│  Listening Ports                                                    │  slow (15s)
│  port · proto · pid · process · project · launcher                  │
└─────────────────────────────────────────────────────────────────────┘
```

**双档刷新**：fast tick 每 3 秒采集 CPU/Memory/Thermal/Battery/AI CLI，slow tick 每 15 秒采集 Top Projects/Ports。每个采集器跑在独立 worker，单个失败不影响其他面板。

<details>
<summary>快捷键</summary>

| 键 | 作用 |
|----|------|
| `q` | 退出 |
| `r` / `R` | 强制快速 / 慢速刷新 |
| `p` | 暂停 / 恢复 |
| `d` | 切换 dry-run |
| `k` / `K` | `SIGTERM` / `SIGKILL` 选中行 |
| `1` / `2` / `3` | 焦点切到 AI CLI / Top Projects / Ports |
| `+` / `-` | fast tick 间隔 ±1 秒 |
| `[` / `]` | slow tick 间隔 ±5 秒 |
| `Tab` / 方向键 | 表内导航 |

</details>

## 进程归因

很多进程监控工具只能告诉你"有一堆 node 在跑"，但说不出"属于哪个项目 / 由谁启动"。`cooldown-my-mac` 用一条 7 级归因链强制每个 dev 进程都拿到归属——`Top Projects` 面板里**永远不会出现 `(cwd unknown)`**。

<details>
<summary>展开：7 级归因链（按严格度从高到低，先到先赢）</summary>

```
┌──────────────────────────────────────────────────────────────────┐
│  1. npx cache / npm exec / 裸 MCP 工具名 → (npx: <pkg>)         │
│     避免 claude / droid 拉起的 MCP 污染项目桶                    │
├──────────────────────────────────────────────────────────────────┤
│  2. find_root(cwd) → 沿 cwd 向上找 15 种 marker（.git /          │
│     package.json / pyproject.toml / Cargo.toml / go.mod / ...）  │
│     命中 monorepo 子目录（apps/web, packages/ui）时跳到 ws 根   │
├──────────────────────────────────────────────────────────────────┤
│  3. _synthesize_app_project → cmdline / cwd 穿过 X.app/ bundle  │
│     → (app: X)，用于归类 Electron helper                         │
├──────────────────────────────────────────────────────────────────┤
│  4. _synthesize_vscode_ext_project → .vscode/extensions/<pub>.  │
│     <name>-<ver> → (vscode: name)                                │
├──────────────────────────────────────────────────────────────────┤
│  5. _synthesize_cmdline_project → 解析 --dir / --cwd / --prefix │
├──────────────────────────────────────────────────────────────────┤
│  6. _synthesize_cwd_project → cwd 磁盘已不存在时从字符串推断    │
│     （~/personal/project/X, ~/work/X, ~/code/X）                │
├──────────────────────────────────────────────────────────────────┤
│  7. _bucket_orphan_project → ppid=1 且 cwd=/ → (orphan)         │
├──────────────────────────────────────────────────────────────────┤
│  兜底 → (background: <argv0>)，按可执行名收容                    │
└──────────────────────────────────────────────────────────────────┘
```

同时对 launcher 沿 ppid 链识别 tmux · cmux · vscode · claude · droid · codex · aider · launchd 等 10+ 种会话类型。

</details>

## 安全模型

- **每个破坏性操作都有 `--dry-run`**，先看要杀谁再决定。
- **自保护**：`cool reap` / `cool apps` 会把调用 `cool` 的进程树全部排除（通过采集 `_self_pid_chain`），不会自杀。
- **Apple 系统进程豁免**：`cool launchd` 硬编码拒绝禁用任何 `com.apple.*` / `gui/501/com.apple.*` 路径下的 agent。
- **oplog 审计日志**：`~/Library/Logs/cooldown/operations.log`，JSON 每行一条，能回溯所有 kill / suspend / bootout。设 `COOL_NO_OPLOG=1` 关掉。
- **默认 SIGTERM + 3 秒超时 + SIGKILL**，给进程正常退场的机会。
- **幂等的 daemon**：`cool daemon install` 可反复跑不会重复注册。

## 与其他工具的关系

`cooldown-my-mac` **不和它们竞争，建议一起用**：

| 工具 | 解决的问题 | 和 cooldown 的分工 |
|------|------|--------------------------|
| [Mole](https://github.com/tw93/Mole) | 磁盘清理 / 一次性优化 | Mole 管磁盘，cooldown 管进程 |
| [mactop](https://github.com/context-labs/mactop) · [macmon](https://github.com/vladkens/macmon) | Apple Silicon 硬件读数（GPU / ANE / 功耗）| 它们看硬件，cooldown 看用户态进程归因 |
| [stats](https://github.com/exelban/stats) | 菜单栏长期驻留 | stats 适合被动一瞥，cooldown 适合"今天怎么又卡了"时主动排查 |
| [btop++](https://github.com/aristocratos/btop) · htop | 通用进程监控 | btop 是通用工具，cooldown 针对 Mac + AI CLI 深度优化 |
| Activity Monitor | macOS 自带 | cooldown 是它的 CLI 表亲，加上项目归因和批量操作 |

## 常见问答

**Q: 会不会杀掉我正在用的 AI CLI 会话？**  
A: 不会。`reap` 默认只动 `idle_seconds >= 1800`（30 分钟无 tty 活动）的进程。自保护链会排除 cool 自身及其所有祖先。不放心先跑 `--dry-run`。

**Q: 为什么要 `sudo purge`？会不会有副作用？**  
A: `purge` 是 macOS 自带命令，清理文件系统的非活跃缓存。唯一"副作用"是接下来几秒文件系统响应慢一点（因为缓存刚清空）。

**Q: Top Projects 里的 `(npx: chrome-devtools-mcp)` 是什么？可以 kill 吗？**  
A: 这是你本地某个 AI CLI（droid / claude / cursor-agent）启动的 MCP 工具，住在 `~/.npm/_npx/` 缓存里。可以安全 kill，AI CLI 下次需要时会自动重新拉起。

**Q: 支持 Intel Mac 吗？**  
A: 支持。P/E 核拓扑会显示成 "NP+0E"（Intel 没有效能核），电池解析做了 Intel 的 deci-kelvin 温度兼容。Apple Silicon 上的电池 / 温度数据更丰富。

## 路线图

未完成：

- [ ] Network 面板（上下行速率 sparkline）
- [ ] Disk Trash / 大文件快速定位
- [ ] 规则引擎 DSL 完善（复合条件、cooldown 周期）
- [ ] `cool dev --kill` 支持按组 kill（整个项目 / 整个 launcher 一键清）

<details>
<summary>已发布（12 条命令）</summary>

`cool status` · `cool watch` · `cool dev` · `cool ports` · `cool procs` · `cool reap` · `cool pressure` · `cool services` · `cool apps` · `cool thermal` · `cool launchd` · `cool daemon`

</details>

## 贡献

欢迎 Issue 和 PR。本地开发：

```bash
.venv/bin/pip install -e ".[watch,dev]"
.venv/bin/python -m pytest tests/ -q       # 全部通过
.venv/bin/python -m ruff check cooldown tests
```

代码风格：Ruff（lint + format）+ 类型注解。新加的收集器 / UI 建议同时加回归测试。

## 许可证

MIT © coldxiangyu
