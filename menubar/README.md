# Coolant · cooldown-my-mac 菜单栏 App

> Your Mac, read like a cockpit — one snowflake tells the truth, and you reach into it to act.

一个原生 SwiftUI 菜单栏应用，是 `cool` CLI 的「第一眼」表现层：常驻菜单栏一片**雪花 + 温度**，点开是一张毛玻璃下拉面板，把 `cool status` 的全部信号——健康 / CPU / 内存 / 电池 / 诊断 / 核心负载 / AI CLI 家族 / 项目占用 / 热进程——按信息密度优先的卡片语言组织起来，并能一键回收 / 清理。

数据层**不重复造轮子**：菜单栏只负责画图，所有采集都 shell out 调用 `cool ... --json`，所以它与终端里的 `cool status` / `cool watch` 永远不会读数打架。

设计方案由 4 个设计 agent 提案 + 设计总监综合而成，完整规格见 [`../docs/menubar-design-spec.md`](../docs/menubar-design-spec.md)；可交互高保真原型（open-design 产出，含旋钮扫读 / 暗亮双色 / Target Mode）见 [`../docs/menubar-prototype/index.html`](../docs/menubar-prototype/index.html)。原型中的旋钮扫读大环、四联表盘在后续实现迭代中被信息密度更高的卡片布局取代（见下）。

## 看点

- **常驻信号**：菜单栏一片雪花 + 紧凑温度数字。健康时渲染成**单色 template 图标**，由系统适配深浅菜单栏、安静得像一只时钟；只有真出问题（pressure critical / thermal warning / 单核 ≥80% on fire / 电池 ≥45°C）才上色变红。
- **现状 hero 卡**：特大号 AI 进程数 + 内存占用一句话归因，数字与卡片渐变跟随健康档位变色（calm 冷色 / warn 琥珀 / critical 红）——颜色是信号，不是装饰。
- **诊断直达处置**：CPU 烤机 / 可回收闲置 / 内存大户 / 内存压力等徽章，能修的一点即达（kill / reap / purge），不能修的只陈述事实；扣分权重与 `cool` 的 `health_score` 完全一致。
- **指标 + 核心负载**：健康 / CPU / 内存 / 电池四枚指标条，**只有越过各自阈值的那枚**染琥珀/红；每颗核心一根负载柱，峰值核心单独标注。
- **热进程**：按 CPU% 排序，单核 ≥80% 的行红条 + 🔥，并自动上移到诊断区之后；行点击展开完整命令行，kill 只走 ✕ 按钮。
- **AI CLI 家族 / 项目占用**：procs 按 kind 聚合成排行条（KIND_COLORS 圆点：claude 品红 / codex 绿 / …），闲置 ≥30 分钟的家族悬停出现回收；项目按 RSS 排行，一键在 Finder 打开。
- **行动页脚**：主操作 `回收闲置 AI`（带实时可回收计数徽标）+ 清理内存（走系统管理员授权）+ 打开 `cool watch` + 刷新。所有破坏性操作都先弹**确认条**，按钮就是动词（终止 / 回收 / 清理），⏎ 才执行。
- **深浅色 + 秒开**：全部配色经 NSColor dynamicProvider 深浅自适应，背板是系统毛玻璃材质；上次采样落盘缓存（Application Support），启动即显示旧数据，不用等首采 ~8 秒。

> 配色 / 阈值（`_pct_color`、`idle_color`、电池温度档、KIND_COLORS、health_score 权重、`shorten_cmd`）全部从 `cooldown/ui/dashboard.py` 移植，保证与 `cool watch` 一致。

## 要求

- macOS 14+（在 macOS 26 Tahoe 上开发，自动吃 Liquid Glass 材质）
- Xcode / Swift 6 工具链（构建用）
- 安装了 `cool`：`pipx install cooldown-my-mac`。App 按 `COOL_BIN` → `~/.local/bin/cool` → Homebrew 路径 →（兜底）登录 shell `command -v cool` 的顺序解析。

## 构建 & 运行

```bash
cd menubar

# 打成可双击的 .app（ad-hoc 签名，LSUIElement 无 dock 图标）→ dist/Cooldown.app
APP_NAME=Cooldown ./build-app.sh
open dist/Cooldown.app

# 或直接跑（开发；用 COOL_BIN 指向源码 venv 里的 cool）
swift build
COOL_BIN="$(cd .. && pwd)/.venv/bin/cool" ./.build/debug/CooldownBar
```

### 调试用的隐藏模式

```bash
CooldownBar selftest             # headless：拉一次真实数据并打印解码结果，验证数据层
CooldownBar render out.png       # 把 popover 用 ImageRenderer 渲染成 PNG（无需屏幕录制权限）
CooldownBar render out.png dark  # 同上，深色模式
CooldownBar preview              # 把 popover 放进普通窗口，方便可视化调试
```

## 结构

```
menubar/
  Package.swift
  build-app.sh                       # 组装 .app + ad-hoc 签名
  Sources/CooldownBar/
    App.swift                        # 入口 / MenuBarExtra / 菜单栏彩色环 / 预览 / 渲染模式
    Model/
      Models.swift                   # cool --json 的 Codable 镜像（全字段可空，兼容 Intel / 无 SMC / 无电池）
      CoolClient.swift               # shell out + 解码 + 二进制解析
      SelfTest.swift                 # headless 自检
      RenderShot.swift               # ImageRenderer 截图
    Views/
      Theme.swift                    # 配色（深浅自适应）/ 字体 / 阈值 / KIND_COLORS / health_score 扣分（CLI 平价）
      Components.swift               # 里程表数字 / 进度条 / 格式化 / shorten_cmd
      RichSections.swift             # hero 现状卡 / 指标条 / 诊断徽章 / 核心负载 / 排行条
      Sections.swift                 # 热进程 / 行动页脚 + Status 派生指标
      ActionRunner.swift             # 确认条（动词按钮）+ reap/purge/kill/watch
      PopoverRootView.swift          # 组装 380pt popover
```

## 已知限制 / 后续

- ImageRenderer 不渲染真实毛玻璃模糊，`render` 截图的材质是平的；真正菜单栏里是系统材质，深浅色随系统切换。
- MenuBarExtra(.window) 在悬停时按像素改变形/尺寸会重入 AppKit 约束周期并崩溃，所以弹层滚动区固定 500pt、hover 只切换布尔状态——源码里相关注释都是 load-bearing，改动需保留这些约束。
- v1 未做设置面板（自定义 `cool` 路径 / 刷新间隔）；原型里的旋钮扫读 / Target Mode / ember 粒子未保留。
- 每个 tick 起两个子进程（`cool status` + `cool thermal`）；后续可把温度折进 `status --json` 降低开销。
