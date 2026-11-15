from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import plistlib
import subprocess
import tempfile
from typing import Any, Callable, Iterator, Optional

import cv2
import numpy as np


CN_BUNDLE_ID = "com.miHoYo.hkrpg"
OVERSEA_BUNDLE_ID = "com.HoYoverse.hkrpgoversea"

DEFAULT_HELPER_PATH = (
    Path(__file__).resolve().parents[2] / "tools" / "macos" / "pc_helper"
)
DEFAULT_PLAYCOVER_APPS_DIR = (
    Path.home() / "Library" / "Containers" / "io.playcover.PlayCover" / "Applications"
)


class CGHelperError(RuntimeError):
    """Raised when pc_helper or screencapture reports an execution or TCC error."""

    def __init__(self, code: str, message: str, exit_code: int = 1) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.exit_code = exit_code


class CGWindowBoundsError(ValueError):
    """Raised when a coordinate maps into the titlebar or outside window bounds."""


@dataclass(frozen=True)
class CGWindowInfo:
    wid: int
    pid: int
    bundle_id: str
    owner: str
    title: str
    x: float
    y: float
    width: float
    height: float
    titlebar_pt: float
    scale_factor: float
    is_active: bool
    is_hidden: bool
    frontmost_bundle_id: Optional[str] = None
    frontmost_pid: Optional[int] = None

    @property
    def content_height(self) -> float:
        return self.height - self.titlebar_pt


def infer_titlebar_pt(width: float, height: float) -> float:
    """Infer PlayCover macOS titlebar height (pt) for a 16:9 game window."""
    if width <= 0 or height <= 0:
        return 0.0
    diff = float(height) - float(width) * (9.0 / 16.0)
    if 20.0 <= diff <= 48.0:
        return diff
    return 0.0


def assert_screen_point_in_content(
    screen_x: float,
    screen_y: float,
    win_x: float,
    win_y: float,
    win_width: float,
    win_height: float,
    titlebar_pt: float = 0.0,
) -> None:
    """Validate that a macOS screen coordinate sits inside the 16:9 game content area."""
    if win_width <= 0 or win_height <= 0 or win_height <= titlebar_pt:
        raise CGWindowBoundsError(
            f"Invalid window geometry width={win_width}, height={win_height}, titlebar={titlebar_pt}"
        )
    eps = 1e-6
    content_top = win_y + titlebar_pt
    win_right = win_x + win_width
    win_bottom = win_y + win_height
    if screen_y < content_top - eps:
        if screen_y >= win_y - eps:
            raise CGWindowBoundsError(
                f"Coordinate y={screen_y:.2f} falls inside titlebar (content starts at {content_top:.2f})"
            )
        raise CGWindowBoundsError(
            f"Coordinate y={screen_y:.2f} is above window top {win_y:.2f}"
        )
    if screen_x < win_x - eps or screen_x > win_right + eps or screen_y > win_bottom + eps:
        raise CGWindowBoundsError(
            f"Coordinate ({screen_x:.2f}, {screen_y:.2f}) is outside window "
            f"[{win_x:.2f}..{win_right:.2f}, {content_top:.2f}..{win_bottom:.2f}]"
        )


def norm_1080_to_screen(
    x: float,
    y: float,
    win_x: float,
    win_y: float,
    win_width: float,
    win_height: float,
    titlebar_pt: float = 0.0,
) -> tuple[float, float]:
    """Map normalized 1920x1080 game coordinates into macOS screen points."""
    if win_width <= 0 or win_height <= 0 or win_height <= titlebar_pt:
        raise CGWindowBoundsError(
            f"Invalid window geometry width={win_width}, height={win_height}, titlebar={titlebar_pt}"
        )
    fx = float(x)
    fy = float(y)
    if fx < 0.0 or fx > 1920.0 or fy < 0.0 or fy > 1080.0:
        raise CGWindowBoundsError(
            f"Normalized coordinate ({fx}, {fy}) out of 1920x1080 content bounds"
        )
    screen_x = float(win_x) + (fx / 1920.0) * float(win_width)
    screen_y = float(win_y) + float(titlebar_pt) + (fy / 1080.0) * (float(win_height) - float(titlebar_pt))
    assert_screen_point_in_content(
        screen_x,
        screen_y,
        float(win_x),
        float(win_y),
        float(win_width),
        float(win_height),
        float(titlebar_pt),
    )
    return screen_x, screen_y


def crop_titlebar_and_resize_1080(
    bgr_img: np.ndarray,
    titlebar_pt: float,
    scale_factor: float = 1.0,
) -> np.ndarray:
    """Strip the PlayCover titlebar in backing pixels and resize content to 1920x1080 BGR."""
    if bgr_img is None or bgr_img.ndim < 2 or bgr_img.shape[0] <= 0 or bgr_img.shape[1] <= 0:
        raise CGWindowBoundsError("Empty capture image")
    crop_top = max(0, int(round(float(titlebar_pt) * float(scale_factor))))
    if crop_top >= bgr_img.shape[0]:
        raise CGWindowBoundsError(
            f"Titlebar crop {crop_top}px exceeds capture height {bgr_img.shape[0]}px"
        )
    content = bgr_img[crop_top:, :] if crop_top > 0 else bgr_img
    h, w = content.shape[:2]
    if w == 1920 and h == 1080:
        return content
    interp = cv2.INTER_AREA if (w > 1920 or h > 1080) else cv2.INTER_LINEAR
    return cv2.resize(content, (1920, 1080), interpolation=interp)


def _read_bundle_id_from_app(app_path: Path) -> Optional[str]:
    info_plist = app_path / "Contents" / "Info.plist"
    if not info_plist.exists():
        # PlayCover wrapped iOS apps sometimes use Info.plist at bundle root or Wrapper/*.app/Info.plist
        direct_plist = app_path / "Info.plist"
        wrapper_dir = app_path / "Wrapper"
        candidates = [direct_plist]
        if wrapper_dir.is_dir():
            candidates.extend(p / "Info.plist" for p in wrapper_dir.glob("*.app"))
        info_plist = next((p for p in candidates if p.exists()), info_plist)
    if not info_plist.exists():
        return None
    try:
        with info_plist.open("rb") as fh:
            data = plistlib.load(fh)
        bid = data.get("CFBundleIdentifier")
        return str(bid) if bid else None
    except Exception:
        return None


def find_playcover_app_path(
    bundle_id: str,
    search_dirs: Optional[list[Path]] = None,
) -> Optional[Path]:
    """Locate an installed PlayCover .app bundle matching bundle_id."""
    dirs = search_dirs or [DEFAULT_PLAYCOVER_APPS_DIR, Path("/Applications")]
    for root in dirs:
        if not root.is_dir():
            continue
        direct = root / f"{bundle_id}.app"
        if direct.exists():
            return direct
        for candidate in sorted(root.glob("*.app")):
            if _read_bundle_id_from_app(candidate) == bundle_id:
                return candidate
    return None


def resolve_playcover_bundle(
    preferred_bundle_id: Optional[str] = None,
    search_dirs: Optional[list[Path]] = None,
) -> tuple[str, Optional[Path]]:
    """Resolve the target HSR PlayCover bundle ID, falling back CN -> Oversea if CN is absent."""
    preferred = (preferred_bundle_id or CN_BUNDLE_ID).strip() or CN_BUNDLE_ID
    direct = find_playcover_app_path(preferred, search_dirs=search_dirs)
    if direct is not None:
        return preferred, direct
    if preferred == CN_BUNDLE_ID:
        fallback = find_playcover_app_path(OVERSEA_BUNDLE_ID, search_dirs=search_dirs)
        if fallback is not None:
            return OVERSEA_BUNDLE_ID, fallback
    return preferred, None


def _match_screen_scale(win_center_x: float, win_center_y: float, screens: list[dict[str, Any]]) -> float:
    for screen in screens:
        sx = float(screen.get("x", 0.0))
        sy = float(screen.get("y", 0.0))
        sw = float(screen.get("width", 0.0))
        sh = float(screen.get("height", 0.0))
        if sx <= win_center_x <= sx + sw and sy <= win_center_y <= sy + sh:
            return float(screen.get("scaleFactor", 2.0) or 2.0)
    for screen in screens:
        if screen.get("isMain"):
            return float(screen.get("scaleFactor", 2.0) or 2.0)
    if screens:
        return float(screens[0].get("scaleFactor", 2.0) or 2.0)
    return 2.0


def _map_key_name(key: str) -> str:
    aliases = {
        "escape": "esc",
        "return": "enter",
        "back": "backspace",
        "del": "delete",
        " ": "space",
    }
    lower = str(key).strip().lower()
    return aliases.get(lower, lower)


class CGPlayCoverClient:
    """macOS CoreGraphics + screencapture transport for Official PlayCover 3.1.0."""

    def __init__(
        self,
        bundle_id: str = CN_BUNDLE_ID,
        restore_focus: bool = True,
        helper_path: Optional[str | Path] = None,
        runner: Optional[Callable[..., subprocess.CompletedProcess[str]]] = None,
    ) -> None:
        self.bundle_id = bundle_id or CN_BUNDLE_ID
        self.restore_focus = bool(restore_focus)
        self.helper_path = Path(helper_path) if helper_path else DEFAULT_HELPER_PATH
        self._runner = runner or subprocess.run
        self._held_prev_pid: Optional[int] = None
        self._last_pointer: tuple[float, float] = (960.0, 540.0)

    def _run_helper(self, *args: str, timeout: float = 10.0) -> dict[str, Any]:
        if not self.helper_path.exists():
            raise CGHelperError(
                "helper_missing",
                f"pc_helper binary not found at {self.helper_path}. Compile tools/macos/pc_helper.swift first.",
                exit_code=127,
            )
        cmd = [str(self.helper_path), *args]
        proc = self._runner(cmd, capture_output=True, text=True, timeout=timeout)
        raw_out = (proc.stdout or proc.stderr or "").strip()
        payload: dict[str, Any] = {}
        if raw_out:
            try:
                payload = json.loads(raw_out)
            except json.JSONDecodeError:
                payload = {"ok": False, "error": "invalid_json", "message": raw_out}
        if proc.returncode != 0 or not payload.get("ok", False):
            err_code = str(payload.get("error") or f"exit_{proc.returncode}")
            err_msg = str(payload.get("message") or raw_out or f"pc_helper exited {proc.returncode}")
            raise CGHelperError(err_code, err_msg, exit_code=proc.returncode)
        return payload

    def tcc_check(self) -> dict[str, Any]:
        return self._run_helper("tcc-check")

    def window_info(self, include_all: bool = False) -> Optional[CGWindowInfo]:
        args = ["window-info", "--bundle", self.bundle_id]
        if include_all:
            args.append("--all")
        data = self._run_helper(*args)
        win = data.get("mainWindow")
        if not isinstance(win, dict):
            return None
        bounds = win.get("bounds") or {}
        width = float(bounds.get("width", 0.0))
        height = float(bounds.get("height", 0.0))
        x = float(bounds.get("x", 0.0))
        y = float(bounds.get("y", 0.0))
        titlebar_pt = infer_titlebar_pt(width, height)
        screens = data.get("screens") or []
        scale = _match_screen_scale(x + width / 2.0, y + height / 2.0, screens)
        return CGWindowInfo(
            wid=int(win["wid"]),
            pid=int(win["pid"]),
            bundle_id=str(win.get("bundleId") or self.bundle_id),
            owner=str(win.get("owner") or ""),
            title=str(win.get("title") or ""),
            x=x,
            y=y,
            width=width,
            height=height,
            titlebar_pt=titlebar_pt,
            scale_factor=scale,
            is_active=bool(win.get("isActive", False)),
            is_hidden=bool(win.get("isHidden", False)),
            frontmost_bundle_id=data.get("frontmostBundleId"),
            frontmost_pid=data.get("frontmostPid"),
        )

    def _require_window(self) -> CGWindowInfo:
        info = self.window_info()
        if info is None or info.wid <= 0:
            raise CGHelperError("window_not_found", f"No active window found for {self.bundle_id}")
        return info

    def is_window_ready(self) -> bool:
        try:
            info = self.window_info()
            return info is not None and info.wid > 0 and info.width > 100 and info.height > 100
        except CGHelperError:
            return False

    def activate(self, wait_ms: int = 250) -> None:
        info = self.window_info(include_all=True)
        if info is not None and info.pid > 0:
            self._run_helper("activate", "--pid", str(info.pid), "--wait-ms", str(wait_ms))
        else:
            self._run_helper("activate", "--bundle", self.bundle_id, "--wait-ms", str(wait_ms))

    def _restore_pid(self, pid: Optional[int]) -> None:
        if pid is None or pid <= 0:
            return
        try:
            self._run_helper("activate", "--pid", str(pid), "--wait-ms", "60")
        except Exception:
            pass

    @contextmanager
    def _activated_target(self, keep_focus: bool = False) -> Iterator[CGWindowInfo]:
        info = self._require_window()
        prev_pid = info.frontmost_pid if info.frontmost_pid and info.frontmost_pid != info.pid else None
        if info.frontmost_pid != info.pid:
            self._run_helper("activate", "--pid", str(info.pid), "--wait-ms", "220")
            # Re-read geometry in case un-minimizing/focus shifted window frame
            info = self._require_window()
        try:
            yield info
        finally:
            if self.restore_focus and not keep_focus and prev_pid is not None:
                self._restore_pid(prev_pid)

    def map_to_screen(self, x: float, y: float, info: Optional[CGWindowInfo] = None) -> tuple[float, float]:
        win = info or self._require_window()
        return norm_1080_to_screen(
            x,
            y,
            win_x=win.x,
            win_y=win.y,
            win_width=win.width,
            win_height=win.height,
            titlebar_pt=win.titlebar_pt,
        )

    def capture_bgr(self) -> Optional[np.ndarray]:
        info = self.window_info()
        if info is None or info.wid <= 0:
            return None
        fd, tmp_path = tempfile.mkstemp(prefix="m7a_cg_", suffix=".png")
        os.close(fd)
        try:
            proc = self._runner(
                ["/usr/sbin/screencapture", "-x", "-o", "-l", str(info.wid), tmp_path],
                capture_output=True,
                text=True,
                timeout=10.0,
            )
            if proc.returncode != 0:
                msg = (proc.stderr or proc.stdout or "").strip()
                raise CGHelperError("screencapture_failed", msg or f"screencapture exited {proc.returncode}", proc.returncode)
            raw = cv2.imread(tmp_path, cv2.IMREAD_COLOR)
            if raw is None:
                raise CGHelperError("capture_decode_failed", f"Failed to read screenshot {tmp_path}")
            scale = (raw.shape[1] / info.width) if (info.width > 0 and raw.shape[1] > 0) else info.scale_factor
            return crop_titlebar_and_resize_1080(raw, info.titlebar_pt, scale_factor=scale)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def click(
        self,
        x: float,
        y: float,
        *,
        hold_ms: int = 45,
        right: bool = False,
        double: bool = False,
    ) -> None:
        with self._activated_target() as info:
            sx, sy = self.map_to_screen(x, y, info=info)
            self._last_pointer = (float(x), float(y))
            args = [
                "click",
                "--x", f"{sx:.2f}",
                "--y", f"{sy:.2f}",
                "--hold-ms", str(max(5, int(hold_ms))),
            ]
            if right:
                args.append("--right")
            if double:
                args.append("--double")
            self._run_helper(*args)

    def mouse_down(self, x: float, y: float, *, right: bool = False) -> None:
        info = self._require_window()
        if self.restore_focus and self._held_prev_pid is None and info.frontmost_pid and info.frontmost_pid != info.pid:
            self._held_prev_pid = info.frontmost_pid
        with self._activated_target(keep_focus=True) as active:
            sx, sy = self.map_to_screen(x, y, info=active)
            self._last_pointer = (float(x), float(y))
            args = ["mouse-down", "--x", f"{sx:.2f}", "--y", f"{sy:.2f}"]
            if right:
                args.append("--right")
            self._run_helper(*args)

    def mouse_move(self, x: float, y: float, *, dragging: bool = False) -> None:
        with self._activated_target(keep_focus=dragging or self._held_prev_pid is not None) as info:
            sx, sy = self.map_to_screen(x, y, info=info)
            self._last_pointer = (float(x), float(y))
            args = ["mouse-move", "--x", f"{sx:.2f}", "--y", f"{sy:.2f}"]
            if dragging:
                args.append("--drag")
            self._run_helper(*args)

    def mouse_up(self, x: Optional[float] = None, y: Optional[float] = None, *, right: bool = False) -> None:
        tx, ty = self._last_pointer if (x is None or y is None) else (float(x), float(y))
        prev_pid = self._held_prev_pid
        self._held_prev_pid = None
        try:
            with self._activated_target(keep_focus=True) as info:
                sx, sy = self.map_to_screen(tx, ty, info=info)
                args = ["mouse-up", "--x", f"{sx:.2f}", "--y", f"{sy:.2f}"]
                if right:
                    args.append("--right")
                self._run_helper(*args)
        finally:
            if self.restore_focus and prev_pid is not None:
                self._restore_pid(prev_pid)

    def drag(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        duration: float = 0.5,
        steps: int = 24,
        pre_hold_ms: int = 70,
        post_hold_ms: int = 80,
    ) -> None:
        with self._activated_target() as info:
            sx1, sy1 = self.map_to_screen(x1, y1, info=info)
            sx2, sy2 = self.map_to_screen(x2, y2, info=info)
            self._last_pointer = (float(x2), float(y2))
            duration_ms = max(40, int(round(float(duration) * 1000.0)))
            timeout = max(10.0, duration + (pre_hold_ms + post_hold_ms) / 1000.0 + 5.0)
            self._run_helper(
                "drag",
                "--x1", f"{sx1:.2f}",
                "--y1", f"{sy1:.2f}",
                "--x2", f"{sx2:.2f}",
                "--y2", f"{sy2:.2f}",
                "--duration-ms", str(duration_ms),
                "--steps", str(max(4, int(steps))),
                "--pre-hold-ms", str(max(10, int(pre_hold_ms))),
                "--post-hold-ms", str(max(10, int(post_hold_ms))),
                timeout=timeout,
            )

    def scroll(self, count: int, x: Optional[float] = None, y: Optional[float] = None) -> None:
        tx, ty = self._last_pointer if (x is None or y is None) else (float(x), float(y))
        with self._activated_target() as info:
            sx, sy = self.map_to_screen(tx, ty, info=info)
            # In macOS CGEvent scroll pixel units, wheel1 positive scrolls up, negative scrolls down;
            # match pyautogui/Windows convention (count > 0 up, count < 0 down) scaled smoothly.
            dy = int(round(float(count) * 40.0))
            self._run_helper(
                "scroll",
                "--x", f"{sx:.2f}",
                "--y", f"{sy:.2f}",
                "--dy", str(dy),
            )

    def key(self, key: str, *, hold_ms: int = 40) -> None:
        mapped = _map_key_name(key)
        with self._activated_target():
            self._run_helper("key", "--key", mapped, "--hold-ms", str(max(10, int(hold_ms))))

    def key_down(self, key: str) -> None:
        mapped = _map_key_name(key)
        info = self._require_window()
        if self.restore_focus and self._held_prev_pid is None and info.frontmost_pid and info.frontmost_pid != info.pid:
            self._held_prev_pid = info.frontmost_pid
        with self._activated_target(keep_focus=True):
            self._run_helper("key-down", "--key", mapped)

    def key_up(self, key: str) -> None:
        mapped = _map_key_name(key)
        prev_pid = self._held_prev_pid
        self._held_prev_pid = None
        try:
            with self._activated_target(keep_focus=True):
                self._run_helper("key-up", "--key", mapped)
        finally:
            if self.restore_focus and prev_pid is not None:
                self._restore_pid(prev_pid)
