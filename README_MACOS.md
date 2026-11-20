# 三月七小助手 macOS 版 Preview（非官方移植 · Apple Silicon + PlayCover）

> [!WARNING]
> **非官方移植与实验性预览声明（Unofficial Port · Experimental Preview）**
> - **非官方社区移植（Unofficial Port）**：本项目是基于上游原版 [moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant)（`GPL-3.0`）构建的**非官方第三方 macOS 移植版**，与原项目作者及官方维护团队无隶属关系。遇到 macOS / PlayCover 相关问题请**仅在本仓库反馈，切勿前往上游原仓库提交 Issue 打扰原作者**。
> - **实验性预览版（Experimental Preview）**：当前仍处于早期实验阶段（Preview），部分界面细节、快捷键与任务流程仍在持续验证和完善中，可能存在未知问题。

适配通过 PlayCover 运行的 iOS/iPad 版《崩坏：星穹铁道》。

---

## 1. 下载安装与首次打开（`.dmg` 独立包）

1. 前往 [Releases](https://github.com/khkjdfkjhdsfakhds/March7thAssistant-macOS/releases) 下载 `March7thAssistant-macOS-v2026.11.20-macos.1-arm64.dmg`。
2. 双击打开 `.dmg`，将 **三月七小助手.app** 拖入 `Applications`（`/Applications`）文件夹。
   - `.app` 已内置完整 Python 3.12 运行时、`PySide6`、`RapidOCR` 离线模型与任务脚本，**无需在本机安装 Homebrew 或配置 Python 环境**。
3. **首次打开（未公证开源应用处理）**：
   - 若 macOS 提示“无法验证开发者 / 已损坏”，可在终端执行：
     ```bash
     xattr -cr "/Applications/三月七小助手.app"
     ```
     或在 **系统设置 → 隐私与安全性** 点击“仍要打开”。
4. **首次运行配置目录**：
   - 独立 `.app` 运行时自动将个人配置与日志保存在可写目录：
     `~/Library/Application Support/March7thAssistant/`（含 `config.yaml` 与 `logs/`）。
   - 首次执行任务前需由用户本人在桌面端确认安全使用须知。

---

## 2. macOS 原生体验亮点

- **macOS 统一通顶毛玻璃侧边栏**：红色/黄色/绿色红绿灯位于左上角侧边栏顶部（`NSVisualEffectMaterialSidebar`），移除 Windows 顶栏图标与窗口控制键。
- **原生窗口与菜单栏行为**：支持 `⌘,`（设置）、`⌘W`（隐藏窗口，点击 Dock 图标重开）、`⌘M`（最小化）、`⌘0`（主窗口）、`⌘L`（任务日志）、`⌘Q`（立即退出），状态栏右键菜单使用原生 `QMenu`。
- **主页卡片化布局**：顶部安全拖拽区、左右对齐的 `12px` 圆角 Banner 与单排任务卡片。

---

## 3. 双传输后端说明（hguandl/PlayCover vs Official PlayCover）

在 `config.yaml`（默认模板见 [assets/config/config.example.yaml](assets/config/config.example.yaml)）中支持三种 `playcover_transport` 模式：

| 模式 | 适用环境 | 截图方式 | 输入与焦点行为 |
|---|---|---|---|
| `auto`（默认） | 兼容两种 PlayCover | 以 **150ms 超时**探测 `127.0.0.1:1717`（MaaTools）；可达则走 `maatools`，否则回退到 `cg` | 自动匹配 |
| `maatools` | `hguandl/PlayCover`（开启 MaaTools 服务 `127.0.0.1:1717`） | MaaTools Socket 抓帧（**100% 纯后台**，不抢窗口焦点） | 通过 Socket 协议模拟触控点击与快捷键映射，不移动系统鼠标；后台拉起游戏（`open -g`） |
| `cg` | **Official PlayCover 3.1.0** | `tools/macos/pc_helper window-info` + `/usr/sbin/screencapture -x -o -l <wid>` 按窗口 ID 后台抓图；自动裁剪顶部标题栏并缩放到 `1920x1080` | 鼠标/滚轮/按键前短暂激活目标 Bundle 投递 Quartz 事件，支持 `playcover_restore_focus: true` 自动恢复原前台应用 |

### TCC 系统权限（仅 `cg` 模式必需）

使用 `cg` 传输时，须在 **系统设置 → 隐私与安全性** 为 `三月七小助手.app`（或运行终端）授权：
1. **屏幕录制（Screen Recording）**
2. **辅助功能（Accessibility）**

使用 `hguandl/PlayCover` 的 `MaaTools:1717` 通道时，确保 PlayCover 内已开启 MaaTools 即可实现纯后台自动化。

---

## 4. 命令行入口（`./m7a` 与 Worker CLI）

```bash
# 查看安装、配置、首次确认状态与传输后端（JSON）
./m7a --status

# 列出可用任务 ID
./m7a --list --json

# 运行日常 / 货币战争（默认 --after-finish None）
./m7a currencywars --after-finish None

# 后台分离运行并实时跟进 / 控制
./m7a currencywars --after-finish None --detach --json
./m7a --follow latest
./m7a --control current pause   # pause / resume / stop
```

### 安全默认值
- `after_finish: "None"`（任务结束后不关机/不退游）；
- 不启用任何充值、商城、星琼换体力、跃迁抽卡或燃料自动消耗；
- `check_update: false`（需更新时前往 GitHub Releases 获取新版本 `.dmg`）。

---

## 5. 从源码构建 `.app` 与 `.dmg`（开发者）

依赖 macOS Xcode Command Line Tools、Homebrew Python 3.12 及 `.venv` 运行依赖：

```bash
# 安装运行与测试依赖
uv sync  # 或使用 .venv/bin/pip install -r requirements.txt

# 1. 构建自包含、可移植的 dist/三月七小助手.app（并同步安装至 /Applications）
bash tools/macos/make_app.sh

# 2. 封装生成 dist/March7thAssistant-macOS-v2026.11.20-macos.1-arm64.dmg 与 SHA256SUMS.txt
bash tools/macos/make_dmg.sh

# 3. 离线测试
.venv/bin/pytest -q tests/test_tasks/test_currency_wars_s2.py tests/test_cg_client.py
```
