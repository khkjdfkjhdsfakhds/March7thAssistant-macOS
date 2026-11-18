#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/assets/config/version.txt")"
APP_NAME="三月七小助手.app"
DIST_APP="$PROJECT_DIR/dist/share/$APP_NAME"
STAGE_DIR="$PROJECT_DIR/dist/dmg_stage"
DMG_NAME="March7thAssistant-macOS-${VERSION}-arm64.dmg"
DMG_PATH="$PROJECT_DIR/dist/$DMG_NAME"
SUMS_PATH="$PROJECT_DIR/dist/SHA256SUMS.txt"

echo "==> Building fresh share edition app via make_app.sh --edition share --dist-only"
bash "$SCRIPT_DIR/make_app.sh" --edition share --dist-only

BUILT_EDITION="$(tr -d '[:space:]' < "$DIST_APP/Contents/Resources/app/assets/config/build_edition.txt" 2>/dev/null || true)"
if [[ "$BUILT_EDITION" != "share" ]]; then
  echo "Error: expected share edition in $DIST_APP, got '$BUILT_EDITION'" >&2
  exit 1
fi

rm -rf "$STAGE_DIR" "$DMG_PATH"
mkdir -p "$STAGE_DIR"

ditto "$DIST_APP" "$STAGE_DIR/$APP_NAME"
ln -s /Applications "$STAGE_DIR/Applications"

cat > "$STAGE_DIR/安装与首次打开说明.txt" <<TXT
三月七小助手 macOS 实验性预览版 (${VERSION} Preview · 非官方移植 Unofficial Port · Apple Silicon)

声明：本应用为上游 moesnow/March7thAssistant 的非官方第三方 macOS 实验性移植预览版（Preview），问题请仅在当前 macOS Fork 仓库反馈，勿打扰原版作者。

一、安装步骤
1. 将「三月七小助手.app」拖入右侧「Applications」文件夹。

二、首次打开（若 macOS 提示“已损坏 / 无法验证开发者”）
本应用使用本地 Ad-Hoc 签名，未购买 Apple 付费开发者公证证书，首次从网络下载可能会被 Gatekeeper 隔离。
方法 A（推荐，终端一行解决）：
  xattr -cr /Applications/三月七小助手.app
方法 B（图形界面）：
  先打开一次（点取消），然后前往「系统设置 -> 隐私与安全性」，拉到下方点击「仍要打开」。

三、权限与用户数据目录
- 首次使用时请按提示授予「辅助功能」与「屏幕录制」权限（控制 PlayCover 游戏窗口所需）。
- 个人配置、日志与运行数据保存在：
  ~/Library/Application Support/March7thAssistant/
TXT

echo "==> Creating $DMG_PATH"
hdiutil create \
  -volname "三月七小助手 ${VERSION}" \
  -srcfolder "$STAGE_DIR" \
  -ov \
  -format UDZO \
  -imagekey zlib-level=9 \
  "$DMG_PATH"

rm -rf "$STAGE_DIR"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -u "$DIST_APP" >/dev/null 2>&1 || true
rm -rf "$DIST_APP"
rmdir "$PROJECT_DIR/dist/share" 2>/dev/null || true

(
  cd "$PROJECT_DIR/dist"
  shasum -a 256 "$DMG_NAME" > "$SUMS_PATH"
)

echo "==> DMG ready: $DMG_PATH"
cat "$SUMS_PATH"
