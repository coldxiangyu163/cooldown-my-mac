# cooldown-my-mac

[English](./README.en.md) · **中文**

<p align="center">
  <img src="./docs/images/cool-watch.png" alt="cool watch dashboard" width="100%">
</p>

<p align="center">
  <b>给重度 Mac 用户的运行时散热 / 负载 CLI</b><br>
  把 24h 挂着的 AI CLI 群（droid · codex · claude · cursor-agent ...）在烤热 Mac 之前清掉。
</p>

<p align="center">
  <a href="https://pypi.org/project/cooldown-my-mac/"><img alt="PyPI" src="https://img.shields.io/pypi/v/cooldown-my-mac.svg"></a>
  <img alt="Python" src="https://img.shields.io/badge/python-3.11%2B-blue">
  <img alt="Platform" src="https://img.shields.io/badge/platform-macOS-black">
  <img alt="Tests" src="https://img.shields.io/badge/tests-passing-brightgreen">
  <img alt="License" src="https://img.shields.io/badge/license-MIT-green">
</p>

---

## 你的 Mac 最近怎么了？

- 风扇响一整天，Activity Monitor 看不出谁在吃 CPU
- 内存压力告警，但不知道哪个忘关的 `next dev` 在吃 4 GB
- 5 个 AI CLI 各启动了一份 MCP 工具，加起来 100+ 个 node 进程
- 重启后又一堆 LaunchAgent / mysql / postgres 自动起来，没人记得为什么

`cool` 是一个 macOS CLI，把每个进程归到「**项目 / AI CLI / 启动器**」三个维度，并提供批量回收、内存压力守护、24/7 launchd 托管。

它**不替代** [Mole](https://github.com/tw93/Mole)（磁盘）/ [mactop](https://github.com/context-labs/mactop)（硬件读数）/ [stats](https://github.com/exelban/stats)（菜单栏）—— 它补上这些工具不管的那块：你的开发工作负载。

## 核心能力

**进程归因 & 识别**
- 每个 dev 进程归到「项目根 + 启动器 + 语言/框架」，7 级 fallback 链兜底（永远不会出现 `cwd unknown`）
- AI CLI 家族识别：droid · codex · claude · opencode · cursor-agent · aider · hermes ... 聚合显示，整族 reap

**硬件感知**
- 电池：ioreg 解析电芯温度 / 循环 / 健康
- SMC：CPU/GPU 温度 + CPU 节流状态
- Apple Silicon P 核 / E 核分别给均值 + 最大值

**自动化 & 守护**
- 内存压力 critical 时自动 `sudo purge` + reap + macOS 通知
- 24/7 launchd 托管 + YAML 规则引擎，幂等安装
- 一键修复 displaysleep / disksleep / 睡眠阻止

**安全 & 可审计**
- 所有破坏性操作支持 `--dry-run`
- JSONL oplog 全量审计（`~/Library/Logs/cooldown/`）
- 自保护进程链 + Apple 系统进程豁免
- 默认 SIGTERM + 3s 宽限 + SIGKILL

**脚本友好**
- `status / procs / dev / ports / thermal` 全部支持 `--json`，可接 `jq` 流水线

## 示例输出

一台日常挂着几个 AI CLI 的 Mac 上 `cool dev` 的真实输出：

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

按使用场景找命令：

| 你想... | 跑 |
|---|---|
| 弹出交互式菜单（Mole 风格） | `cool` |
| 看 Mac 整体健康 | `cool status` |
| 打开全屏实时仪表盘 | `cool watch` |
| 找出最吃资源的 AI CLI 会话 | `cool procs` |
| 一次清掉所有闲置 30 分钟以上的 AI CLI | `cool reap` |
| 看每个 dev 进程属于哪个项目 / 哪个 launcher 拉起 | `cool dev` |
| 查谁占着 5432 端口 | `cool ports 5432` |
| 内存压力高时自动清理 | `cool pressure --watch --auto-reap --auto-purge --yes` |
| 24/7 后台守护 | `cool daemon install` |
| 输出 JSON 喂给脚本 | `cool status --json \| jq` |

## 命令一览

所有命令都接 `--help` 看完整 flag，下面只列最常用的几条。

**实时仪表盘 `cool watch`** — 双档刷新：fast tick 每 3s 采 CPU/Memory/Thermal/Battery/AI CLI，slow tick 每 15s 采 Top Projects/Ports。截图见[顶部](#cooldown-my-mac)。

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

<details>
<summary>cool watch 快捷键</summary>

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

**开发栈洞察 `cool dev` · `cool ports`**
```bash
cool dev                          # 按项目分组：RSS / CPU / 闲置 / launcher
cool dev --by launcher --stale    # 按启动器看孤儿和老项目；--kill 进交互
cool ports 5432                   # 5432 被谁占了？--free 4000:4100 看空闲
```

**进程回收 `cool procs` · `cool reap`** — 自保护 + SIGTERM/3s/SIGKILL + [oplog](#实现细节)
```bash
cool procs                        # 列所有 AI CLI / 终端复用器，多选 kill
cool reap --dry-run               # 预览要回收的 ≥30 分钟闲置 AI CLI / tmux
cool reap --kinds droid,claude --yes        # 限定家族 + 免确认
```

**内存压力 `cool pressure`**
```bash
cool pressure --watch -n 60                                     # 持续监控
cool pressure --watch --auto-reap --auto-purge --notify --yes   # 24h 守护组合
```

**服务 & 应用 `cool services` · `cool apps`**
```bash
cool services stop mysql postgres -y                  # 开发服务批量停
cool apps suspend --kind wechat --kind dingtalk -y    # IM SIGSTOP（不退出，省 CPU）
cool apps resume --kind wechat -y                     # SIGCONT 恢复
```

**温度 / launchd / 守护 `cool thermal` · `cool launchd` · `cool daemon`**
```bash
cool thermal --restore            # 恢复 displaysleep / disksleep / 允许睡眠
cool launchd --audit --disable    # 列第三方 agent + 交互式 bootout（Apple 拒禁）
cool daemon install               # 注册 24/7 守护到 ~/Library/LaunchAgents/
```

<details>
<summary>YAML 规则配置示例（<code>~/.config/cooldown/config.yaml</code>）</summary>

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

## 实现细节

两个常被问到的内部机制——展开看：

<details>
<summary>进程归因：7 级链，<code>Top Projects</code> 永远不会出现 <code>cwd unknown</code></summary>

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

<details>
<summary>安全细节：oplog 路径、自保护链、Apple 豁免</summary>

「核心能力」里已列出四道安全防线，下面是补充：

- **oplog 路径**：`~/Library/Logs/cooldown/operations.log`，JSONL 每行一条，记录每次 kill / suspend / bootout。设 `COOL_NO_OPLOG=1` 关掉。
- **Apple 进程豁免范围**：`cool launchd` 拒绝禁用任何匹配 `com.apple.*` / `gui/501/com.apple.*` 的 agent。
- **自保护实现**：`_self_pid_chain` 从调用进程沿 ppid 一路收到 init，整条链都不会被 reap / apps 命中。
- **幂等 daemon**：`cool daemon install` 可反复跑，不会重复注册。

</details>

## 常见问答

**Q: 会不会杀掉我正在用的 AI CLI 会话？**  
A: 不会。`reap` 默认只动 `idle_seconds >= 1800`（30 分钟无 tty 活动）的进程。自保护链会排除 cool 自身及其所有祖先。不放心先跑 `--dry-run`。

**Q: 为什么要 `sudo purge`？会不会有副作用？**  
A: `purge` 是 macOS 自带命令，清理文件系统的非活跃缓存。唯一"副作用"是接下来几秒文件系统响应慢一点（因为缓存刚清空）。

**Q: 支持 Intel Mac 吗？**  
A: 支持。P/E 核拓扑会显示成 "NP+0E"（Intel 没有效能核），电池解析做了 Intel 的 deci-kelvin 温度兼容。Apple Silicon 上的电池 / 温度数据更丰富。

## 路线图

- [ ] Network 面板（上下行速率 sparkline）
- [ ] Disk Trash / 大文件快速定位
- [ ] 规则引擎 DSL 完善（复合条件、cooldown 周期）
- [ ] `cool dev --kill` 支持按组 kill（整个项目 / 整个 launcher 一键清）

<details>
<summary>和其他 Mac 工具的分工对照</summary>

`cooldown-my-mac` **不和它们竞争，建议一起用**：

| 工具 | 解决的问题 | 和 cooldown 的分工 |
|------|------|--------------------------|
| [Mole](https://github.com/tw93/Mole) | 磁盘清理 / 一次性优化 | Mole 管磁盘，cooldown 管进程 |
| [mactop](https://github.com/context-labs/mactop) · [macmon](https://github.com/vladkens/macmon) | Apple Silicon 硬件读数（GPU / ANE / 功耗）| 它们看硬件，cooldown 看用户态进程归因 |
| [stats](https://github.com/exelban/stats) | 菜单栏长期驻留 | stats 适合被动一瞥，cooldown 适合"今天怎么又卡了"时主动排查 |
| [btop++](https://github.com/aristocratos/btop) · htop | 通用进程监控 | btop 是通用工具，cooldown 针对 Mac + AI CLI 深度优化 |
| Activity Monitor | macOS 自带 | cooldown 是它的 CLI 表亲，加上项目归因和批量操作 |

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
