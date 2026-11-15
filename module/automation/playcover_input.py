import math
import subprocess
import threading
import time

import cv2

from module.automation.input_base import InputBase
from module.game.maatools_client import TouchPhase
from module.mobile import profile

# 手指编号 不同编号互相独立 可以同时按住（MaaTools 多指触控）
CONTACT_TAP = 0
CONTACT_JOYSTICK = 1
CONTACT_BUTTON = 2

MOVE_KEYS = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}


class PlayCoverInput(InputBase):
    """
    把 PC 键鼠操作转换成 iOS PlayCover 操作（支持 MaaTools 与 CoreGraphics 双后端）

    - maatools: 进程内注入 UITouch（纯后台，多指独立）
    - cg: CoreGraphics 激活 PlayCover 窗口后映射 16:9 内容坐标（防 PlayTools brk #0x1），并可按配置恢复焦点
    """

    def __init__(self, game, logger):
        self.game = game
        self.logger = logger
        self._lock = threading.RLock()
        self._cursor = (960, 540)
        self._mouse_pressed = False
        self._cg_joystick_pressed = False
        self._move_pressed: set[str] = set()
        self._button_pressed: str | None = None
        self._templates = {}

    def _is_cg(self) -> bool:
        return self.game.active_transport() == "cg"

    # ---------- 基础触控 ----------

    def _touch(self, phase: TouchPhase, x: float, y: float, contact: int) -> bool:
        tx, ty = self.game.to_touch(x, y)
        return self.game.client.touch(phase, tx, ty, contact)

    def tap(self, x: float, y: float, press_time: float = 0.05, contact: int = CONTACT_TAP) -> None:
        with self._lock:
            self._cursor = (x, y)
            if self._is_cg():
                self.game.cg_client.click(x, y, hold_ms=max(20, int(round(press_time * 1000))))
                return
            self._touch(TouchPhase.BEGAN, x, y, contact)
            time.sleep(max(press_time, 0.03))
            self._touch(TouchPhase.ENDED, x, y, contact)

    def swipe(self, start, end, duration: float = 0.5, contact: int = CONTACT_TAP, hold_end: float = 0.1) -> None:
        with self._lock:
            self._cursor = (end[0], end[1])
            if self._is_cg():
                self.game.cg_client.drag(
                    start[0],
                    start[1],
                    end[0],
                    end[1],
                    duration=max(float(duration or 0), 0.12),
                    post_hold_ms=max(20, int(round(float(hold_end) * 1000))),
                )
                return
            steps = max(int(duration / 0.016), 5)
            self._touch(TouchPhase.BEGAN, start[0], start[1], contact)
            time.sleep(0.05)
            for i in range(1, steps + 1):
                t = i / steps
                self._touch(
                    TouchPhase.MOVED,
                    start[0] + (end[0] - start[0]) * t,
                    start[1] + (end[1] - start[1]) * t,
                    contact,
                )
                time.sleep(duration / steps)
            time.sleep(hold_end)
            self._touch(TouchPhase.ENDED, end[0], end[1], contact)

    def release_all(self) -> None:
        with self._lock:
            if self._is_cg():
                if self._mouse_pressed or self._cg_joystick_pressed or self._button_pressed is not None:
                    try:
                        self.game.cg_client.mouse_up()
                    except Exception:
                        pass
                self._cg_joystick_pressed = False
            else:
                for contact in (CONTACT_TAP, CONTACT_JOYSTICK, CONTACT_BUTTON):
                    self._touch(TouchPhase.ENDED, *self._cursor, contact)
            self._mouse_pressed = False
            self._move_pressed.clear()
            self._button_pressed = None

    # ---------- 鼠标 ----------

    def mouse_click(self, x, y):
        self.tap(x, y)
        self.logger.debug(f"触控点击 ({x}, {y})")

    def mouse_down(self, x, y):
        with self._lock:
            self._cursor = (x, y)
            self._mouse_pressed = True
            if self._is_cg():
                self.game.cg_client.mouse_down(x, y)
            else:
                self._touch(TouchPhase.BEGAN, x, y, CONTACT_TAP)
            self.logger.debug(f"触控按下 ({x}, {y})")

    def mouse_up(self):
        with self._lock:
            if self._is_cg():
                self.game.cg_client.mouse_up(*self._cursor)
            else:
                self._touch(TouchPhase.ENDED, *self._cursor, CONTACT_TAP)
            self._mouse_pressed = False
            self.logger.debug("触控抬起")

    def mouse_move(self, x, y):
        with self._lock:
            if self._mouse_pressed:
                if self._is_cg():
                    self.game.cg_client.mouse_move(x, y, dragging=True)
                else:
                    self.swipe_to(x, y)
            elif self._is_cg():
                self.game.cg_client.mouse_move(x, y, dragging=False)
            self._cursor = (x, y)

    def swipe_to(self, x, y, duration=0.2):
        sx, sy = self._cursor
        if self._is_cg():
            self.game.cg_client.mouse_move(x, y, dragging=True)
            self._cursor = (x, y)
            return
        steps = max(int(duration / 0.016), 3)
        for i in range(1, steps + 1):
            t = i / steps
            self._touch(TouchPhase.MOVED, sx + (x - sx) * t, sy + (y - sy) * t, CONTACT_TAP)
            time.sleep(duration / steps)
        self._cursor = (x, y)

    def mouse_drag(self, start_x, start_y, end_x, end_y, duration=0.5, end_pause=0.0, repeats=1):
        drag_duration = max(float(duration or 0), 0.2)
        hold_end = max(float(end_pause or 0), 0.1)
        for idx in range(max(1, int(repeats))):
            self.swipe((start_x, start_y), (end_x, end_y), duration=drag_duration, hold_end=hold_end)
            if idx + 1 < repeats and end_pause:
                time.sleep(float(end_pause))
        self._cursor = (end_x, end_y)
        self.logger.debug(f"触控拖动 ({start_x}, {start_y}) -> ({end_x}, {end_y})")
        return True

    def mouse_scroll(self, count, direction=-1, pause=True):
        """
        鼠标滚轮转换成在光标位置的滑动或 CGEvent 滚轮。
        direction=-1 是向下滚动。
        """
        rule = self._scroll_rule()
        if not rule and self._is_cg():
            signed = abs(int(count)) * (1 if direction >= 0 else -1)
            self.game.cg_client.scroll(signed, *self._cursor)
            self.logger.debug(f"CG 滚轮 {signed} @ {self._cursor}")
            if pause:
                time.sleep(0.3)
            return

        step = float(rule.get("step", profile().get("scroll_step", 60)))
        max_distance = float(rule.get("max_distance", 600))
        total = step * count
        sign = -1 if direction < 0 else 1
        x, y = rule.get("at", self._cursor)
        for _ in range(min(max(math.ceil(total / max_distance), 1), 5)):
            distance = min(total, max_distance)
            total -= distance
            if rule.get("axis") == "horizontal":
                start = (x - sign * distance / 2, y)
                end = (x + sign * distance / 2, y)
            elif rule:
                start = (x, y - sign * distance / 2)
                end = (x, y + sign * distance / 2)
            else:
                start = (x, y)
                end = (x, min(max(y + sign * distance, 10), 1070))
            self.swipe(start, end, duration=0.4 + 0.02 * count, hold_end=0.3)
            self.logger.debug(f"触控滚动 {count} 次 方向 {direction} {start} -> {end}")
            if total <= 0:
                break
        if pause:
            time.sleep(0.3)

    def _rule_matches(self, rule: dict, screen) -> bool:
        from module import mobile
        template = mobile.read_template(rule["template"])
        if template is None:
            return False
        x, y, w, h = rule.get("region", [0, 0, 1920, 1080])
        part = screen[y:y + h, x:x + w]
        if part.shape[0] < template.shape[0] or part.shape[1] < template.shape[1]:
            return False
        return cv2.matchTemplate(part, template, cv2.TM_CCOEFF_NORMED).max() >= rule.get("threshold", 0.85)

    def _first_matching_rule(self, rules: list) -> dict:
        if not rules:
            return {}
        screen = self.game.screenshot_bgr()
        if screen is None:
            return {}
        for rule in rules:
            if self._rule_matches(rule, screen):
                return rule
        return {}

    def _scroll_rule(self) -> dict:
        return self._first_matching_rule(profile().get("scroll_rules", []))

    def press_mouse(self, wait_time=0.2):
        target = "attack"
        rules = profile().get("attack_alternatives", [])
        screen = self.game.screenshot_bgr() if rules else None
        if screen is not None:
            from module.ocr import ocr
            for rule in rules:
                x, y, w, h = rule["region"]
                part = cv2.cvtColor(screen[y:y + h, x:x + w], cv2.COLOR_BGR2RGB)
                result = ocr.recognize_single_line(part)
                if result and rule["text"] in result[0]:
                    self.logger.debug(f"左键 → {rule['text']} {rule['tap']}")
                    target = rule["tap"]
                    break
        self._press_button(target, wait_time)

    # ---------- 键盘 ----------

    @staticmethod
    def _normalize_key(key) -> str:
        key = str(key).lower()
        return {"escape": "esc", "space": "space"}.get(key, key)

    def _key_target(self, key: str):
        rules = [rule for rule in profile().get("key_rules", []) if key in rule.get("keys", {})]
        rule = self._first_matching_rule(rules)
        if rule:
            return rule["keys"][key]
        return profile().get("keys", {}).get(key)

    def press_key(self, key, wait_time=0.2):
        key = self._normalize_key(key)
        if key in MOVE_KEYS:
            self.press_key_down(key)
            time.sleep(wait_time)
            self.press_key_up(key)
        elif key == "esc":
            self.back()
        else:
            target = self._key_target(key)
            if target is None:
                self.logger.warning(f"移动端没有按键 {key} 对应的按钮 已忽略")
                return
            self._press_button(target, min(wait_time, 0.3))
        self.logger.debug(f"按键 {key}")

    def secretly_press_key(self, key, wait_time=0.2):
        key = self._normalize_key(key)
        if key in MOVE_KEYS or key == "esc":
            self.press_key(key, wait_time)
            return
        target = self._key_target(key)
        if target is not None:
            self._press_button(target, min(wait_time, 0.3))

    def press_key_down(self, key):
        key = self._normalize_key(key)
        if key in MOVE_KEYS:
            self._move_pressed.add(key)
            self._update_joystick(began=len(self._move_pressed) == 1)
            return
        target = self._key_target(key)
        if target is None:
            self.logger.debug(f"移动端没有按键 {key} 对应的按钮 已忽略")
            return
        point = self._button_point(target)
        if point is not None:
            self._button_pressed = target["button"] if isinstance(target, dict) else target
            if self._is_cg():
                self.game.cg_client.mouse_down(point[0], point[1])
            else:
                self._touch(TouchPhase.BEGAN, point[0], point[1], CONTACT_BUTTON)

    def press_key_up(self, key):
        key = self._normalize_key(key)
        if key in MOVE_KEYS:
            if key in self._move_pressed:
                self._move_pressed.discard(key)
                if self._move_pressed:
                    self._update_joystick(began=False)
                else:
                    center = profile()["touch"]["joystick"]
                    if self._is_cg():
                        if self._cg_joystick_pressed:
                            self.game.cg_client.mouse_up(center[0], center[1])
                            self._cg_joystick_pressed = False
                    else:
                        self._touch(TouchPhase.ENDED, center[0], center[1], CONTACT_JOYSTICK)
            return
        target = self._key_target(key)
        if isinstance(target, dict):
            target = target["button"]
        if target is not None and self._button_pressed == target:
            point = self._button_point(target)
            if self._is_cg():
                self.game.cg_client.mouse_up(point[0], point[1])
            else:
                self._touch(TouchPhase.ENDED, point[0], point[1], CONTACT_BUTTON)
            self._button_pressed = None

    def _update_joystick(self, began: bool) -> None:
        center = profile()["touch"]["joystick"]
        radius = float(profile()["touch"].get("joystick_radius", 120))
        dx = sum(MOVE_KEYS[k][0] for k in self._move_pressed)
        dy = sum(MOVE_KEYS[k][1] for k in self._move_pressed)
        length = math.hypot(dx, dy) or 1
        x = center[0] + dx / length * radius
        y = center[1] + dy / length * radius
        if self._is_cg():
            if began or not self._cg_joystick_pressed:
                self.game.cg_client.mouse_down(center[0], center[1])
                self._cg_joystick_pressed = True
                time.sleep(0.05)
            for t in ((0.4, 1.0) if began else (1.0,)):
                self.game.cg_client.mouse_move(
                    center[0] + (x - center[0]) * t,
                    center[1] + (y - center[1]) * t,
                    dragging=True,
                )
                time.sleep(0.02)
            return
        if began:
            self._touch(TouchPhase.BEGAN, center[0], center[1], CONTACT_JOYSTICK)
            time.sleep(0.05)
            for t in (0.3, 0.6, 1.0):
                self._touch(TouchPhase.MOVED, center[0] + (x - center[0]) * t, center[1] + (y - center[1]) * t, CONTACT_JOYSTICK)
                time.sleep(0.02)
        else:
            self._touch(TouchPhase.MOVED, x, y, CONTACT_JOYSTICK)

    def _button_point(self, target):
        if isinstance(target, dict):
            target = target["button"]
        if isinstance(target, (list, tuple)):
            return target
        point = profile()["touch"].get(target)
        if point is None:
            self.logger.warning(f"移动端触控布局缺少按钮 {target}")
        return point

    def _press_button(self, target, press_time: float = 0.1) -> None:
        point = self._button_point(target)
        if point is not None:
            self.tap(point[0], point[1], press_time=press_time, contact=CONTACT_BUTTON)
            if isinstance(target, dict) and target.get("wait"):
                time.sleep(float(target["wait"]))

    # ---------- Esc ----------

    def _template(self, name: str):
        if name not in self._templates:
            from utils.image_utils import ImageUtils
            self._templates[name] = ImageUtils.read_image(f"./assets/mobile/images/ui/{name}.png")
        return self._templates[name]

    def _match(self, screen, name: str, region, threshold: float = 0.8):
        x, y, w, h = region
        part = screen[y:y + h, x:x + w]
        template = self._template(name)
        if template is None or part.shape[0] < template.shape[0] or part.shape[1] < template.shape[1]:
            return None
        result = cv2.matchTemplate(part, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        if max_val < threshold:
            return None
        return x + max_loc[0] + template.shape[1] // 2, y + max_loc[1] + template.shape[0] // 2

    def _ocr_texts(self, screen, region):
        from module.ocr import ocr
        x, y, w, h = region
        part = cv2.cvtColor(screen[y:y + h, x:x + w], cv2.COLOR_BGR2RGB)
        results = ocr.convert_format(ocr.run(part)) or []
        return [(box, text) for box, (text, _) in results], (x, y)

    def _match_text(self, screen, item):
        if "when" in item:
            texts, _ = self._ocr_texts(screen, item.get("when_region", [0, 0, 1920, 1080]))
            if not any(item["when"] in text for _, text in texts):
                return None
        texts, (ox, oy) = self._ocr_texts(screen, item["region"])
        for box, text in texts:
            if item["text"] in text:
                return ox + (box[0][0] + box[2][0]) / 2, oy + (box[0][1] + box[2][1]) / 2
        return None

    def back(self) -> None:
        screen = self.game.screenshot_bgr()
        if screen is not None:
            for item in profile().get("back_buttons", []):
                if "text" in item:
                    pos = self._match_text(screen, item)
                else:
                    pos = self._match(screen, item["template"], item["region"], item.get("threshold", 0.8))
                if pos is not None:
                    self.logger.debug(f"Esc → 点击 {item.get('template') or item['text']} {pos}")
                    self.tap(*pos)
                    return
        fallback = profile()["touch"].get("back_fallback")
        if fallback:
            self.logger.debug(f"Esc → 未识别到返回按钮 点击默认位置 {fallback}")
            self.tap(*fallback)

    # ---------- 文字 ----------

    def secretly_write(self, text, interval=0.1):
        subprocess.run(["pbcopy"], input=str(text).encode("utf-8"), check=False)
        self._paste_by_shortcut()

    def _paste_by_shortcut(self) -> None:
        if self._is_cg():
            try:
                self.game.cg_client.activate(wait_ms=300)
                self.game.cg_client._run_helper("key", "--key", "v", "--modifiers", "cmd", "--hold-ms", "40")
                return
            except Exception as e:
                self.logger.warning(f"CG Cmd+V 失败：{e}")
        try:
            import AppKit
            import Quartz
        except ImportError:
            self.logger.warning("缺少 pyobjc 无法发送 Cmd+V 请手动粘贴")
            return
        apps = AppKit.NSRunningApplication.runningApplicationsWithBundleIdentifier_(self.game.bundle_id)
        if not apps:
            return
        previous = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
        apps[0].activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
        time.sleep(0.4)
        for down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, 9, down)
            Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
            Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
            time.sleep(0.03)
        time.sleep(0.3)
        if previous is not None and previous.bundleIdentifier() != self.game.bundle_id:
            previous.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps)
