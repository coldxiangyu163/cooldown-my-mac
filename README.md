# cooldown-my-mac

[English](./README.en.md) · **中文**

为重度 Mac 用户准备的**运行时**散热 / 负载管理工具，专门照顾那些 24 小时挂着一堆 AI CLI（droid、codex、claude、opencode……）的开发场景。

> 和 [Mole](https://github.com/tw93/Mole) 互补：Mole 侧重磁盘清理和一次性优化；cooldown-my-mac 盯的是**实时负载**——清理僵尸 agent、做内存压力保护、驯服休眠 / 温控策略、还能做成 launchd agent 7×24 跑在后台。

## 安装

```bash
pipx install cooldown-my-mac
# 可选：启用 cool watch 全屏实时仪表盘
pipx inject cooldown-my-mac textual
```

会注册两个命令：`cool`（短）和 `cooldown`（完整别名）。

> 本地开发时推荐用源码仓库的 `.venv`：  
> `alias cool='/path/to/cooldown-my-mac/.venv/bin/cool'`  
> 这样改完代码立刻生效，不用 pipx 重装。

## 常用命令

```bash
cool                              # 交互菜单（Mole 风格）
cool status                       # 一次性健康快照
cool watch                        # 全屏实时仪表盘（Textual）

# 开发栈洞察：我的 node/python 是谁起的？属于哪个项目？占了哪些端口？
cool dev                          # 按项目分组（默认）
cool dev --by launcher            # 按拉起者分组（tmux / droid / vscode / ...）
cool dev --by lang                # node=N python=M ruby=K ...
cool dev --stale                  # 只看孤儿 + 陈旧项目的进程
cool dev --project macool         # 过滤到某个项目
cool dev --kill                   # 交互式 kill 选择器
cool ports                        # 所有监听端口（过滤 Apple 系统）+ pid / 项目归因
cool ports 5432                   # 5432 被谁占了？
cool ports 4000:5000              # 端口区间查询
cool ports --conflict             # 找同一端口被多个 pid 占用的冲突
cool ports --free 4000:4100       # 查一段区间内还空着哪些端口
cool ports --kill                 # 选端口 → 杀掉占用进程

# AI CLI / 进程管理
cool procs                        # 交互多选 kill
cool reap                         # 回收闲置的 droid / codex / claude / tmux 会话
cool reap --dry-run               # 预览
cool reap --kind codex --ai-idle 1800

# 内存压力
cool pressure                     # 一次评估
cool pressure --watch -n 60 --notify
cool pressure --auto-reap --auto-purge --yes

# 本地服务 + 大胃口 GUI
cool services                     # mysql / postgres / redis / nanobot / hermes 开关
cool apps list
cool apps suspend --kind wechat --kind dingtalk -y
cool apps resume --kind wechat -y

# 温度 + 休眠策略 + launchd 审计
cool thermal
cool thermal --restore            # 恢复 displaysleep / disksleep = 10 分钟
cool launchd                      # 概览
cool launchd --audit --disable    # 交互 bootout 选择器

# 7×24 后台规则引擎
cool daemon config-init
cool daemon install               # 写入 ~/Library/LaunchAgents/ai.cooldown.agent.plist
cool daemon status
cool daemon logs
cool daemon uninstall
```

破坏性操作一律要求确认。全部行为会落日志到 `~/Library/Logs/cooldown/operations.log`（设 `COOL_NO_OPLOG=1` 关掉）。

## 安全保障

- 每个 kill / suspend / disable 都有 `--dry-run` 模式。
- `cool reap` 和 `cool apps` 会保护调用者自身及其所有祖先进程。
- `cool launchd` 拒绝禁用任何 Apple 自家的 agent。
- `cool daemon` 幂等，`install` 可以反复跑。

## `cool watch` 界面结构

新版 Textual 仪表盘布局（灵感来自 `mo status`，再结合项目归因）：

```
┌───────────────────────────────────────────────────────────────────┐
│ Health ●74 · MacBook Pro · M1 Max, 32GPU 8P+2E · 64G/1.8T · …    │  ← 顶部单行 header
├───────────────┬───────────────────────────────────────────────────┤
│     CPU       │     Memory        │                               │
│  P / E 核拆分 │  Used / Swap / 压力                               │
├───────────────┼───────────────────┤
│   Thermal     │     Battery       │  电量 · 温度 · 健康 · 循环     │
├───────────────┼───────────────────┤
│  AI CLI 清单  │  Top Projects RSS │  按项目归因的 RSS 排行         │
├───────────────┴───────────────────┤
│        Listening Ports            │  端口 + pid + 项目 + launcher  │
└───────────────────────────────────┘
```

**快捷键**：`q` 退出 · `r` 快速刷新 · `R` 慢速刷新 · `p` 暂停 · `d` 切到 dry-run · `k` 杀选中行 · `K` 强杀 · `1/2/3` 焦点切换到 AI / Projects / Ports 表 · `+/-` 调快慢、`[/]` 调慢速 tick。

## 路线图

- [x] `cool status` — 一次性仪表盘（含 Top Projects by RSS）
- [x] `cool watch` — 全屏实时 Textual 仪表盘 + P/E 核 + 电池面板
- [x] `cool dev` — 开发栈（node / python / ruby / go / java / ...）清单 + **项目 & 拉起者归因**
- [x] `cool ports` — 监听端口地图 + pid / 进程 / 项目归因
- [x] `cool procs` — AI CLI 清单 + 交互 kill
- [x] `cool reap` — 闲置会话回收器
- [x] `cool pressure` — 内存压力守卫（含 watch / 自动 reap / 自动 purge / 通知）
- [x] `cool services` — 本地开发服务开关
- [x] `cool apps` — IM / GUI 应用挂起 & 恢复
- [x] `cool thermal` — 温度面板 + 休眠策略恢复
- [x] `cool launchd` — launchd 审计 + 选择性 bootout
- [x] `cool daemon` — launchd 托管的规则引擎

## 许可证

MIT
