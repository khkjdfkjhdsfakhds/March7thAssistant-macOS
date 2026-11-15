---
name: march7th-assistant
description: 操作 macOS PlayCover 版「三月七小助手 / March7thAssistant / M7A」（《崩坏：星穹铁道》自动化工具）：查看状态与任务、运行日常/清体力/货币战争（S2 入画奇航）/差分宇宙/模拟宇宙等任务，或核查配置与双传输后端。
license: GPL-3.0
---

# 三月七小助手（macOS PlayCover）

- **项目目录**：`<仓库根目录>`（独立 `.app` 安装路径为 `/Applications/三月七小助手.app`）
- **CLI 入口**：`./m7a`（或独立包 `/Applications/三月七小助手.app/Contents/Helpers/March7thWorker.app/Contents/MacOS/March7thWorker /Applications/三月七小助手.app/Contents/Resources/app/main.py`）

## 常用 CLI 命令

```bash
./m7a --status                          # 状态、首次确认、传输与最近运行（JSON）
./m7a --list --json                     # 列出支持任务（routine/daily/power/currencywars/divergent 等）
./m7a <TASK> --after-finish None        # 运行任务并保持完成后不关机/不退游
./m7a <TASK> --after-finish None --detach --json  # 后台启动并返回 run_id
./m7a --follow latest                   # 跟进最近一次运行输出
./m7a --control current pause           # 控制运行中任务：pause / resume / stop
```

## 安全与调度约定

1. **先查状态再动手**：若 `--status` 中 `first_run_completed` 为 `false`，须由用户本人在 GUI（`/Applications/三月七小助手.app`）确认免责声明，**严禁代为确认或绕过**；若 `active_run` 非空，避免并发操控游戏。
2. **默认保留 `--after-finish None`**：严禁开启充值、商城、星琼换体力、抽卡，亦禁止未经要求开启燃料/后备体力或绕过 macOS TCC。
3. **macOS 配置与运行说明**：参见 [README_MACOS.md](../../../README_MACOS.md)。
