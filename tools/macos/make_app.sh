#!/usr/bin/env bash
set -euo pipefail

DIST_ONLY=0
EDITION="local"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dist-only)
      DIST_ONLY=1
      shift
      ;;
    --edition)
      if [[ $# -lt 2 ]]; then
        echo "Missing argument for --edition (expected local|share)" >&2
        exit 2
      fi
      EDITION="$2"
      shift 2
      ;;
    --edition=*)
      EDITION="${1#*=}"
      shift
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

case "$EDITION" in
  local|share)
    ;;
  *)
    echo "Invalid --edition: $EDITION (expected local|share)" >&2
    exit 2
    ;;
esac

if [[ "$EDITION" == "share" ]]; then
  # 分享版只在独立目录输出，避免误覆盖 /Applications 的本地自用版
  DIST_ONLY=1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python"
PY_SITE="$VENV_DIR/lib/python3.12/site-packages"

if [[ ! -x "$VENV_PY" ]]; then
  echo "Error: missing virtualenv Python at $VENV_PY" >&2
  exit 1
fi

PY_FW_SRC="/opt/homebrew/opt/python@3.12/Frameworks/Python.framework"
if [[ ! -d "$PY_FW_SRC/Versions/3.12" ]] && command -v brew >/dev/null 2>&1; then
  PY_FW_SRC="$(brew --prefix python@3.12)/Frameworks/Python.framework"
fi
if [[ ! -d "$PY_FW_SRC/Versions/3.12" ]]; then
  echo "Error: missing Python.framework 3.12 at $PY_FW_SRC" >&2
  exit 1
fi

VERSION="$(tr -d '[:space:]' < "$PROJECT_DIR/assets/config/version.txt")"
SHORT_VERSION="${VERSION#v}"
APP_NAME="三月七小助手.app"
if [[ "$EDITION" == "share" ]]; then
  DIST_APP="$PROJECT_DIR/dist/share/$APP_NAME"
else
  DIST_APP="$PROJECT_DIR/dist/$APP_NAME"
fi
CONTENTS="$DIST_APP/Contents"
WORKER_APP="$CONTENTS/Helpers/March7thWorker.app"
INSTALL_APP="/Applications/$APP_NAME"

echo "==> [1/8] Compiling pc_helper.swift"
swiftc -O \
  -framework AppKit \
  -framework ApplicationServices \
  -framework CoreGraphics \
  "$PROJECT_DIR/tools/macos/pc_helper.swift" \
  -o "$PROJECT_DIR/tools/macos/pc_helper"
chmod +x "$PROJECT_DIR/tools/macos/pc_helper"

echo "==> [2/8] Preparing bundle skeleton at $DIST_APP"
mkdir -p "$(dirname "$DIST_APP")"
touch "$PROJECT_DIR/dist/.metadata_never_index"
rm -rf "$DIST_APP"
mkdir -p \
  "$CONTENTS/MacOS" \
  "$CONTENTS/Resources/app" \
  "$CONTENTS/Resources/site-packages" \
  "$CONTENTS/Frameworks" \
  "$WORKER_APP/Contents/MacOS" \
  "$WORKER_APP/Contents/Resources"

echo "==> [3/8] Building AppIcon.icns"
ICONSET_TMP="$(mktemp -d "${TMPDIR:-/tmp}/m7a_iconset.XXXXXX")"
ICONSET_DIR="$ICONSET_TMP/AppIcon.iconset"
mkdir -p "$ICONSET_DIR"
"$VENV_PY" - "$PROJECT_DIR" "$ICONSET_DIR" <<'PY'
import os
import sys
from PIL import Image

project_dir, iconset_dir = sys.argv[1], sys.argv[2]
ico_path = os.path.join(project_dir, "assets", "logo", "March7th.ico")
jpg_path = os.path.join(project_dir, "assets", "app", "images", "March7th.jpg")
src_path = ico_path if os.path.exists(ico_path) else jpg_path

img = Image.open(src_path).convert("RGBA")
specs = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]
for filename, size in specs:
    resized = img.resize((size, size), Image.Resampling.LANCZOS)
    resized.save(os.path.join(iconset_dir, filename), format="PNG")
PY
iconutil -c icns "$ICONSET_DIR" -o "$CONTENTS/Resources/AppIcon.icns"
rm -rf "$ICONSET_TMP"

echo "==> [4/8] Copying clean app code & runtime assets (edition: $EDITION)"
for item in app module tasks utils assets 3rdparty; do
  rsync -a \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude '.DS_Store' \
    "$PROJECT_DIR/$item/" "$CONTENTS/Resources/app/$item/"
done
printf '%s\n' "$EDITION" > "$CONTENTS/Resources/app/assets/config/build_edition.txt"
mkdir -p "$CONTENTS/Resources/app/tools/macos"
cp "$PROJECT_DIR/tools/macos/pc_helper" "$CONTENTS/Resources/app/tools/macos/pc_helper"
chmod +x "$CONTENTS/Resources/app/tools/macos/pc_helper"

for root_file in app.py main.py m7a LICENSE README_MACOS.md; do
  if [[ -f "$PROJECT_DIR/$root_file" ]]; then
    cp "$PROJECT_DIR/$root_file" "$CONTENTS/Resources/app/$root_file"
  fi
done
chmod +x "$CONTENTS/Resources/app/m7a"

if [[ -e "$CONTENTS/Resources/app/config.yaml" ]]; then
  echo "Error: config.yaml leaked into bundle!" >&2
  exit 1
fi

echo "==> [5/8] Embedding & relocating Python.framework 3.12"
FW_DEST="$CONTENTS/Frameworks/Python.framework"
mkdir -p "$FW_DEST/Versions/3.12"
rsync -a --delete \
  --exclude '__pycache__' \
  --exclude '*.pyc' \
  --exclude 'Headers' \
  --exclude 'include' \
  --exclude 'share' \
  --exclude 'bin' \
  --exclude '_CodeSignature' \
  --exclude 'Resources/Python.app' \
  --exclude 'lib/pkgconfig' \
  --exclude 'lib/libpython3.12.a' \
  --exclude 'lib/python3.12/config-3.12-darwin' \
  --exclude 'lib/python3.12/site-packages' \
  --exclude 'lib/python3.12/test' \
  --exclude 'lib/python3.12/idlelib' \
  --exclude 'lib/python3.12/ensurepip' \
  --exclude 'lib/python3.12/pydoc_data' \
  --exclude 'lib/python3.12/lib2to3' \
  --exclude 'lib/python3.12/turtledemo' \
  --exclude 'lib/python3.12/tkinter' \
  --exclude '_ctypes_test*.so' \
  --exclude '_test*.so' \
  --exclude '_xxtestfuzz*.so' \
  --exclude '_tkinter*.so' \
  "$PY_FW_SRC/Versions/3.12/" "$FW_DEST/Versions/3.12/"

ln -sfn "3.12" "$FW_DEST/Versions/Current"
ln -sfn "Versions/Current/Python" "$FW_DEST/Python"
ln -sfn "Versions/Current/Resources" "$FW_DEST/Resources"
chmod +w "$FW_DEST/Versions/3.12/Python"

install_name_tool -id "@rpath/Python.framework/Versions/3.12/Python" "$FW_DEST/Versions/3.12/Python"
while IFS= read -r rpath_entry; do
  if [[ "$rpath_entry" == /opt/homebrew* || "$rpath_entry" == /usr/local* || "$rpath_entry" == /Users/* ]]; then
    install_name_tool -delete_rpath "$rpath_entry" "$FW_DEST/Versions/3.12/Python" || true
  fi
done < <(otool -l "$FW_DEST/Versions/3.12/Python" | awk '$1 == "cmd" && $2 == "LC_RPATH" {found=2} found && $1 == "path" {print $2; found=0}')

echo "==> [6/8] Relocating Homebrew dylibs & copying slimmed site-packages"
SITE_DEST="$CONTENTS/Resources/site-packages"
export M7A_PY_SITE="$PY_SITE"
export M7A_SITE_DEST="$SITE_DEST"
export M7A_DIST_APP="$DIST_APP"
export M7A_FRAMEWORKS="$CONTENTS/Frameworks"

"$VENV_PY" - <<'PY'
import glob
import os
import re
import shutil
import stat
import subprocess

py_site = os.environ["M7A_PY_SITE"]
site_dest = os.environ["M7A_SITE_DEST"]
frameworks_dir = os.environ["M7A_FRAMEWORKS"]

keep_pyobjc = {
    "AVFAudio",
    "AVFoundation",
    "AppKit",
    "ApplicationServices",
    "Cocoa",
    "CoreAudio",
    "CoreFoundation",
    "CoreMedia",
    "CoreText",
    "ExceptionHandling",
    "Foundation",
    "HIServices",
    "MediaPlayer",
    "Network",
    "PyObjCTools",
    "Quartz",
    "SystemConfiguration",
}

all_pyobjc_dirs = set()
keep_pyobjc_distinfos = set()
for di in glob.glob(os.path.join(py_site, "pyobjc_framework_*.dist-info")):
    di_name = os.path.basename(di)
    rec = os.path.join(di, "RECORD")
    tops = set()
    if os.path.exists(rec):
        with open(rec, encoding="utf-8", errors="ignore") as f:
            for line in f:
                top = line.split("/", 1)[0]
                if top and not top.endswith(".dist-info") and os.path.isdir(os.path.join(py_site, top)):
                    tops.add(top)
    all_pyobjc_dirs.update(tops)
    if tops & keep_pyobjc:
        keep_pyobjc_distinfos.add(di_name)

keep_qt_modules = {
    "QtCore",
    "QtDBus",
    "QtGui",
    "QtWidgets",
    "QtNetwork",
    "QtSvg",
    "QtSvgWidgets",
    "QtXml",
    "QtOpenGL",
}

keep_qt_plugins = {
    "platforms": {"libqcocoa.dylib", "libqminimal.dylib", "libqoffscreen.dylib"},
    "styles": {"libqmacstyle.dylib"},
    "imageformats": None,  # all except libqpdf.dylib
    "iconengines": {"libqsvgicon.dylib"},
    "tls": {"libqsecuretransportbackend.dylib", "libqopensslbackend.dylib", "libqcertonlybackend.dylib"},
    "networkinformation": {"libqapplenetworkinformation.dylib"},
}

skip_top_names = {
    "__pycache__",
    "__editable__",
    "_pytest",
    "pytest",
    "iniconfig",
    "pluggy",
    "py.py",
    "pip",
    "PyObjCTest",
    "PySide6",
}
skip_prefixes = (
    "pytest-",
    "iniconfig-",
    "pluggy-",
    "pip-",
    "pyside6_pdf-",
    "pyside6_webengine-",
)

def ignore_pycache(_dir, names):
    return [n for n in names if n == "__pycache__" or n.endswith(".pyc") or n == ".DS_Store"]

for entry in sorted(os.listdir(py_site)):
    src = os.path.join(py_site, entry)
    dst = os.path.join(site_dest, entry)

    if entry in skip_top_names:
        continue
    if entry == ".DS_Store" or entry.endswith(".pyc"):
        continue
    if entry.startswith(skip_prefixes):
        continue
    if entry.startswith("pyobjc_framework_") and entry not in keep_pyobjc_distinfos:
        continue
    if entry in all_pyobjc_dirs and entry not in keep_pyobjc:
        continue

    if os.path.isdir(src):
        shutil.copytree(src, dst, symlinks=True, ignore=ignore_pycache)
    else:
        shutil.copy2(src, dst)

# Copy slimmed PySide6
ps_src = os.path.join(py_site, "PySide6")
ps_dst = os.path.join(site_dest, "PySide6")
os.makedirs(ps_dst, exist_ok=True)

for name in ("__init__.py", "_config.py", "_git_pyside_version.py", "py.typed"):
    p = os.path.join(ps_src, name)
    if os.path.exists(p):
        shutil.copy2(p, os.path.join(ps_dst, name))

support_src = os.path.join(ps_src, "support")
if os.path.isdir(support_src):
    shutil.copytree(support_src, os.path.join(ps_dst, "support"), symlinks=True, ignore=ignore_pycache)

for entry in os.listdir(ps_src):
    if entry.startswith("libpyside6.abi3") and entry.endswith(".dylib"):
        shutil.copy2(os.path.join(ps_src, entry), os.path.join(ps_dst, entry))

for mod in keep_qt_modules:
    so_path = os.path.join(ps_src, f"{mod}.abi3.so")
    if os.path.exists(so_path):
        shutil.copy2(so_path, os.path.join(ps_dst, f"{mod}.abi3.so"))

qt_lib_dst = os.path.join(ps_dst, "Qt", "lib")
os.makedirs(qt_lib_dst, exist_ok=True)
for mod in keep_qt_modules:
    fw_src = os.path.join(ps_src, "Qt", "lib", f"{mod}.framework")
    fw_dst = os.path.join(qt_lib_dst, f"{mod}.framework")
    if os.path.isdir(fw_src):
        shutil.copytree(fw_src, fw_dst, symlinks=True, ignore=ignore_pycache)

plugins_src = os.path.join(ps_src, "Qt", "plugins")
plugins_dst = os.path.join(ps_dst, "Qt", "plugins")
for category, allow in keep_qt_plugins.items():
    cat_src = os.path.join(plugins_src, category)
    if not os.path.isdir(cat_src):
        continue
    cat_dst = os.path.join(plugins_dst, category)
    os.makedirs(cat_dst, exist_ok=True)
    for fname in os.listdir(cat_src):
        if fname == "libqpdf.dylib" or not fname.endswith(".dylib"):
            continue
        if allow is None or fname in allow:
            shutil.copy2(os.path.join(cat_src, fname), os.path.join(cat_dst, fname))

# Relocate any non-system shared library references in embedded Python.framework
def macho_files(root):
    out = []
    for base, _dirs, files in os.walk(root):
        for f in files:
            p = os.path.join(base, f)
            if os.path.islink(p):
                continue
            if f.endswith((".so", ".dylib")) or "/Versions/" in p and f == os.path.basename(os.path.dirname(os.path.dirname(p))):
                out.append(p)
    return out

def get_deps(path):
    res = subprocess.check_output(["otool", "-L", path], text=True)
    deps = []
    for line in res.splitlines()[1:]:
        dep = line.strip().split(" (", 1)[0]
        if dep:
            deps.append(dep)
    return deps

def ensure_writable(path):
    st = os.stat(path).st_mode
    os.chmod(path, st | stat.S_IWUSR)

copied_dylibs = {}
queue = macho_files(os.path.join(os.environ["M7A_DIST_APP"], "Contents", "Frameworks", "Python.framework"))
visited = set()

while queue:
    target = queue.pop(0)
    if target in visited:
        continue
    visited.add(target)

    deps = get_deps(target)
    changed = False
    for dep in deps:
        if dep.startswith(("/opt/homebrew/", "/usr/local/", "/Users/")):
            bname = os.path.basename(dep)
            dst_dylib = os.path.join(frameworks_dir, bname)
            if bname not in copied_dylibs:
                real_dep = os.path.realpath(dep)
                shutil.copy2(real_dep, dst_dylib)
                ensure_writable(dst_dylib)
                subprocess.check_call(["install_name_tool", "-id", f"@rpath/{bname}", dst_dylib])
                copied_dylibs[bname] = dst_dylib
                queue.append(dst_dylib)
            ensure_writable(target)
            subprocess.check_call(["install_name_tool", "-change", dep, f"@rpath/{bname}", target])
            changed = True

    if changed and target.endswith(".so") and "lib-dynload" in target:
        rel_rpath = "@loader_path/../../../../../.."
        out_l = subprocess.check_output(["otool", "-l", target], text=True)
        if rel_rpath not in out_l:
            subprocess.check_call(["install_name_tool", "-add_rpath", rel_rpath, target])
    if target.startswith(frameworks_dir + os.sep) and target.endswith(".dylib"):
        out_l = subprocess.check_output(["otool", "-l", target], text=True)
        if "@loader_path" not in out_l:
            ensure_writable(target)
            subprocess.check_call(["install_name_tool", "-add_rpath", "@loader_path", target])

# Strip any non-relocatable LC_RPATHs across Frameworks and site-packages
def get_bad_rpaths(path):
    res = subprocess.check_output(["otool", "-l", path], text=True, stderr=subprocess.DEVNULL)
    rpaths = []
    in_rpath = False
    for line in res.splitlines():
        s = line.strip()
        if s == "cmd LC_RPATH":
            in_rpath = True
        elif in_rpath and s.startswith("path "):
            val = s.split(" ", 1)[1].split(" (offset", 1)[0]
            if val.startswith(("/opt/homebrew", "/usr/local/", "/Users/")):
                if val not in rpaths:
                    rpaths.append(val)
            in_rpath = False
    return rpaths

for scan_root in (frameworks_dir, site_dest):
    for mfile in macho_files(scan_root):
        try:
            bad_rpaths = get_bad_rpaths(mfile)
        except Exception:
            continue
        if bad_rpaths:
            ensure_writable(mfile)
            for rp in bad_rpaths:
                subprocess.check_call(["install_name_tool", "-delete_rpath", rp, mfile])
PY

echo "==> [7/8] Compiling native launchers & writing Info.plist files"
PY_INCLUDES="$(/opt/homebrew/opt/python@3.12/bin/python3.12-config --includes)"

# shellcheck disable=SC2086
clang -O2 -arch arm64 -mmacosx-version-min=13.0 \
  $PY_INCLUDES \
  -DM7A_GUI_MODE=1 \
  "$PROJECT_DIR/tools/macos/native_launcher.c" \
  "$FW_DEST/Versions/3.12/Python" \
  -ldl -framework CoreFoundation \
  -Wl,-rpath,@executable_path/../Frameworks \
  -o "$CONTENTS/MacOS/March7thAssistant"

# shellcheck disable=SC2086
clang -O2 -arch arm64 -mmacosx-version-min=13.0 \
  $PY_INCLUDES \
  -DM7A_GUI_MODE=0 \
  "$PROJECT_DIR/tools/macos/native_launcher.c" \
  "$FW_DEST/Versions/3.12/Python" \
  -ldl -framework CoreFoundation \
  -Wl,-rpath,@executable_path/../../../../Frameworks \
  -o "$WORKER_APP/Contents/MacOS/March7thWorker"

chmod +x "$CONTENTS/MacOS/March7thAssistant" "$WORKER_APP/Contents/MacOS/March7thWorker"
printf 'APPL????' > "$CONTENTS/PkgInfo"
printf 'APPL????' > "$WORKER_APP/Contents/PkgInfo"

cat > "$CONTENTS/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>三月七小助手</string>
  <key>CFBundleExecutable</key>
  <string>March7thAssistant</string>
  <key>CFBundleIconFile</key>
  <string>AppIcon</string>
  <key>CFBundleIdentifier</key>
  <string>top.m7a.March7thAssistant</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>三月七小助手</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${SHORT_VERSION}</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>NSAppleEventsUsageDescription</key>
  <string>三月七小助手需要通过自动化和系统事件控制 PlayCover 游戏窗口。</string>
</dict>
</plist>
PLIST

cat > "$WORKER_APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key>
  <string>zh_CN</string>
  <key>CFBundleDisplayName</key>
  <string>March7thWorker</string>
  <key>CFBundleExecutable</key>
  <string>March7thWorker</string>
  <key>CFBundleIdentifier</key>
  <string>top.m7a.March7thAssistant.worker</string>
  <key>CFBundleInfoDictionaryVersion</key>
  <string>6.0</string>
  <key>CFBundleName</key>
  <string>March7thWorker</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleShortVersionString</key>
  <string>${SHORT_VERSION}</string>
  <key>CFBundleVersion</key>
  <string>1</string>
  <key>LSMinimumSystemVersion</key>
  <string>13.0</string>
  <key>LSUIElement</key>
  <true/>
</dict>
</plist>
PLIST

echo "==> [8/8] Auditing Mach-O & privacy, signing inside-out"
CURRENT_USER="${USER:-$(id -un)}"
if [[ -n "$CURRENT_USER" ]] && grep -rnI "$CURRENT_USER" "$CONTENTS/Resources/app" >/dev/null 2>&1; then
  echo "Error: found personal username in bundle Resources/app!" >&2
  exit 1
fi

"$VENV_PY" - "$DIST_APP" <<'PY'
import os
import subprocess
import sys

dist_app = sys.argv[1]
bad = []
for base, _dirs, files in os.walk(dist_app):
    for f in files:
        p = os.path.join(base, f)
        if os.path.islink(p):
            continue
        try:
            with open(p, "rb") as fp:
                magic = fp.read(4)
        except OSError:
            continue
        if magic not in (
            b"\xcf\xfa\xed\xfe",
            b"\xfe\xed\xfa\xcf",
            b"\xca\xfe\xba\xbe",
            b"\xbe\xba\xfe\xca",
        ):
            continue
        out_L = subprocess.check_output(["otool", "-L", p], text=True, stderr=subprocess.DEVNULL)
        for line in out_L.splitlines():
            if not line.startswith(("\t", " ")):
                continue
            dep = line.strip().split(" (", 1)[0]
            if "/opt/homebrew" in dep or "/Users/" in dep or "/usr/local/" in dep:
                bad.append(f"{p}: {dep}")

        out_l = subprocess.check_output(["otool", "-l", p], text=True, stderr=subprocess.DEVNULL)
        for line in out_l.splitlines():
            s = line.strip()
            if s.startswith(("name ", "path ")):
                val = s.split(" ", 1)[1].split(" (offset", 1)[0]
                if "/opt/homebrew" in val or "/Users/" in val or "/usr/local/" in val:
                    bad.append(f"{p}: {s}")
if bad:
    print("Error: non-relocatable Mach-O references found:", file=sys.stderr)
    for item in bad[:30]:
        print(" ", item, file=sys.stderr)
    sys.exit(1)
PY

find "$DIST_APP" -type l ! -exec test -e {} \; -delete
xattr -cr "$DIST_APP"

find "$DIST_APP" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 | xargs -0 -n1 codesign --force --sign -
if [[ -f "$SITE_DEST/selenium/webdriver/common/macos/selenium-manager" ]]; then
  codesign --force --sign - "$SITE_DEST/selenium/webdriver/common/macos/selenium-manager"
fi
for fw in "$SITE_DEST/PySide6/Qt/lib/"*.framework; do
  codesign --force --sign - "$fw"
done
codesign --force --sign - "$FW_DEST/Versions/3.12"
codesign --force --sign - "$FW_DEST"
codesign --force --sign - "$CONTENTS/Resources/app/tools/macos/pc_helper"
codesign --force --sign - "$WORKER_APP"
codesign --force --sign - "$DIST_APP"

codesign -vv --deep --strict "$DIST_APP"
echo "Build complete: $DIST_APP"

if [[ "$DIST_ONLY" -eq 0 ]]; then
  echo "==> Installing to $INSTALL_APP"
  if pgrep -f "/Applications/$APP_NAME/Contents/MacOS/March7thAssistant" >/dev/null 2>&1; then
    osascript -e 'tell application id "top.m7a.March7thAssistant" to quit' >/dev/null 2>&1 || true
    for _ in $(seq 1 16); do
      if ! pgrep -f "/Applications/$APP_NAME/Contents/MacOS/March7thAssistant" >/dev/null 2>&1; then
        break
      fi
      sleep 0.5
    done
  fi
  if pgrep -f "/Applications/$APP_NAME/Contents/MacOS/March7thAssistant" >/dev/null 2>&1; then
    echo "Error: existing $APP_NAME is still running; quit it before installing." >&2
    exit 1
  fi

  rm -rf "$INSTALL_APP"
  ditto "$DIST_APP" "$INSTALL_APP"
  codesign -vv --deep --strict "$INSTALL_APP"

  USER_DATA_DIR="$HOME/Library/Application Support/March7thAssistant"
  mkdir -p "$USER_DATA_DIR"
  if [[ ! -f "$USER_DATA_DIR/config.yaml" && -f "$PROJECT_DIR/config.yaml" ]]; then
    cp "$PROJECT_DIR/config.yaml" "$USER_DATA_DIR/config.yaml"
    chmod 600 "$USER_DATA_DIR/config.yaml"
  fi

  LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
  "$LSREGISTER" -u "$DIST_APP" >/dev/null 2>&1 || true
  "$LSREGISTER" -u "$PROJECT_DIR/dist/share/$APP_NAME" >/dev/null 2>&1 || true
  rm -rf "$DIST_APP" "$PROJECT_DIR/dist/share/$APP_NAME"
  "$LSREGISTER" -f "$INSTALL_APP" >/dev/null 2>&1 || true
  echo "Installed: $INSTALL_APP"
fi
