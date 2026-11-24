# 三月七小助手 macOS 实验性预览版 (March7thAssistant-macOS · Preview)

> [!WARNING]
> **非官方移植与实验性预览声明（Unofficial Port · Experimental Preview）**
>
> 本仓库是 [moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant) 的 **非官方第三方 macOS（Apple Silicon）实验性预览移植版**，与原版作者及官方团队无关联，目前仍处于 **Preview / 实验阶段**，接口、打包形态与功能行为可能继续调整。
>
> **请勿将任何 macOS / PlayCover / 打包相关的 Issue 或崩溃反馈提交至原版仓库 [moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant)**；相关问题请仅在本仓库反馈。

面向 Apple Silicon（arm64）Mac 的开箱即用独立应用包，配合 **PlayCover** 运行《崩坏：星穹铁道》iOS 版，支持基于 `hguandl/PlayCover` (`MaaTools:1717`) 的纯后台自动化执行与原生 macOS 界面体验。

---

## 1. 下载安装与首次打开

1. 前往本仓库 [Releases (Pre-release)](https://github.com/khkjdfkjhdsfakhds/March7thAssistant-macOS/releases) 下载 **`March7thAssistant-macOS-v2026.11.24-macos.1-arm64.dmg`**（及 `SHA256SUMS.txt` 校验）。
2. 双击挂载 DMG 后，将 **`三月七小助手.app`** 拖入 **`/Applications`**（应用程序）。
3. **本应用包完全独立（Self-Contained）**：内置精简 Apple Silicon `Python 3.12`、`PySide6`、`PyObjC`、`RapidOCR` 及所有动态库，**无需本机安装 Homebrew 或 Python**。
4. 由于预览版暂未经过 Apple Developer 公证（仅带 Ad-hoc 签名），首次打开若出现“已损坏”或“无法验证开发者”提示，请在终端执行一次隔离属性清理后重新打开：

```bash
xattr -cr "/Applications/三月七小助手.app"
open "/Applications/三月七小助手.app"
```

---

## 2. macOS 原生界面亮点（Preview）

- **标准 macOS 窗口样式**：采用全高通顶毛玻璃侧边栏、左上角标准红绿灯控制按钮，以及安全的顶部间距与圆角横幅卡片布局。
- **单排清晰导航与卡片适配**：优化深浅色模式自适应对比度、工具栏对齐与卡片密度。
- **原生菜单栏与快捷键**：支持 `Cmd+,` 打开设置、`Cmd+W` 隐藏窗口、Dock 图标点击恢复主界面。

---

## 3. 双传输后端（PlayCover）

| 传输模式 | 依赖版本 | 特性 | 是否需要 macOS TCC 权限 |
| --- | --- | --- | --- |
| **`maatools`（默认推荐）** | [hguandl/PlayCover](https://github.com/hguandl/PlayCover)（`MaaTools:1717`） | **纯后台运行**：不抢占前台窗口焦点、不移动系统鼠标指针 | 一般无需辅助功能指针注入；截图失败时可按需补充屏幕录制或改用 `cg` |
| **`cg`** | 官方版 PlayCover / 通用 macOS 窗口 | `ScreenCaptureKit` / `CGWindowListCreateImage` 截图 + `CGEvent` 后台键鼠投递 | 需要授权 **屏幕录制（Screen Recording）** 与 **辅助功能（Accessibility）** |

在应用设置或 `config.yaml` 中可通过 `playcover_transport: auto`（优先尝试 `maatools:1717`，不可用时按配置回退）切换模式；首次运行前请先阅读并同意应用内的首次使用免责声明。

---

## 4. 用户数据目录

macOS 独立应用版（`.app` Bundle 只读不可自改写）将配置、运行日志、OCR/运行时缓存统一保存在：

```text
~/Library/Application Support/March7thAssistant/
├── config.yaml
└── logs/
```

---

## 5. 命令行与从源码构建

### 命令行入口

```bash
# 查看当前状态、版本与配置文件位置
./m7a --status

# 执行自动化任务（示例：货币战争且完成后不关闭游戏）
./m7a currencywars --after-finish None
```

### 从源码构建 `.app` 与 `.dmg`

在已完成依赖初始化（`.venv` 就绪）的 Apple Silicon macOS 环境中：

```bash
# 构建独立 Apple Silicon 应用并安装到 /Applications/三月七小助手.app
bash tools/macos/make_app.sh

# 打包发布用压缩 DMG 与 SHA256SUMS.txt
bash tools/macos/make_dmg.sh
```

详细原理、双通道细节、权限排查与构建审计清单请参阅 [README_MACOS.md](README_MACOS.md)。

---

## 6. 相关文档与许可

- macOS 移植详细说明：[README_MACOS.md](README_MACOS.md)
- 上游原版完整文档（Windows 端原版功能说明）：[README_UPSTREAM.md](README_UPSTREAM.md)
- 开源许可证：遵循上游 [GPL-3.0 License](LICENSE)

### 致谢

- 原版项目与核心功能实现：[moesnow/March7thAssistant](https://github.com/moesnow/March7thAssistant)
- PlayCover 后台自动化协议支持：[hguandl/PlayCover](https://github.com/hguandl/PlayCover)
