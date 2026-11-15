import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import cv2
import numpy as np
import pytest

from module.game.cg_client import (
    CGHelperError,
    CGPlayCoverClient,
    CGWindowBoundsError,
    CN_BUNDLE_ID,
    OVERSEA_BUNDLE_ID,
    assert_screen_point_in_content,
    crop_titlebar_and_resize_1080,
    infer_titlebar_pt,
    norm_1080_to_screen,
    resolve_playcover_bundle,
)
from module.game.playcover import PlayCoverGameController


class _DictConfig:
    def __init__(self, **values):
        self.script_path = str(Path.cwd())
        self.values = dict(values)

    def get_value(self, key, default=None):
        return self.values.get(key, default)


def test_infer_titlebar_pt_playcover_geometries():
    assert infer_titlebar_pt(1478, 859) == pytest.approx(27.625)
    assert infer_titlebar_pt(1280, 744) == pytest.approx(24.0)
    assert infer_titlebar_pt(1280, 720) == 0.0
    assert infer_titlebar_pt(1920, 1080) == 0.0
    assert infer_titlebar_pt(0, 720) == 0.0


def test_norm_1080_to_screen_mapping_and_bounds():
    # Window at (100, 50), 1478x859 with 27.625pt titlebar -> content height 831.375
    win = (100.0, 50.0, 1478.0, 859.0, 27.625)
    sx0, sy0 = norm_1080_to_screen(0.0, 0.0, *win)
    assert sx0 == pytest.approx(100.0)
    assert sy0 == pytest.approx(77.625)

    sx_mid, sy_mid = norm_1080_to_screen(960.0, 540.0, *win)
    assert sx_mid == pytest.approx(100.0 + 739.0)
    assert sy_mid == pytest.approx(50.0 + 27.625 + 831.375 / 2.0)

    sx_end, sy_end = norm_1080_to_screen(1920.0, 1080.0, *win)
    assert sx_end == pytest.approx(1578.0)
    assert sy_end == pytest.approx(909.0)


def test_norm_1080_to_screen_rejects_titlebar_and_out_of_window():
    with pytest.raises(CGWindowBoundsError):
        norm_1080_to_screen(960, -1, 100, 50, 1280, 744, 24.0)
    with pytest.raises(CGWindowBoundsError):
        norm_1080_to_screen(-0.1, 500, 100, 50, 1280, 744, 24.0)
    with pytest.raises(CGWindowBoundsError):
        norm_1080_to_screen(1920.1, 500, 100, 50, 1280, 744, 24.0)
    with pytest.raises(CGWindowBoundsError):
        norm_1080_to_screen(500, 1080.1, 100, 50, 1280, 744, 24.0)
    with pytest.raises(CGWindowBoundsError):
        assert_screen_point_in_content(500.0, 60.0, 100.0, 50.0, 1280.0, 744.0, 24.0)
    with pytest.raises(CGWindowBoundsError):
        assert_screen_point_in_content(1400.0, 500.0, 100.0, 50.0, 1280.0, 744.0, 24.0)


def test_crop_titlebar_and_resize_1080_downscales_and_upscales():
    # Retina 2x shot of 1478x859 window -> 2956x1718, top 55px is titlebar (27.625 * 2 = 55.25 -> 55)
    raw = np.zeros((1718, 2956, 3), dtype=np.uint8)
    raw[:55, :, :] = (0, 0, 255)
    raw[55:, :, :] = (0, 255, 0)
    out = crop_titlebar_and_resize_1080(raw, 27.625, scale_factor=2.0)
    assert out.shape == (1080, 1920, 3)
    assert out[0, 0].tolist() == [0, 255, 0]

    # Normalized 1280x744 (24px titlebar at 1x) -> strip 24 -> 1280x720 -> resize 1920x1080
    raw_1x = np.zeros((744, 1280, 3), dtype=np.uint8)
    raw_1x[:24, :, :] = (255, 0, 0)
    raw_1x[24:, :, :] = (10, 20, 30)
    out_1x = crop_titlebar_and_resize_1080(raw_1x, 24.0, scale_factor=1.0)
    assert out_1x.shape == (1080, 1920, 3)
    assert out_1x[0, 0].tolist() == [10, 20, 30]


def test_resolve_playcover_bundle_cn_to_oversea_fallback(tmp_path):
    apps = tmp_path / "Applications"
    apps.mkdir()
    oversea = apps / f"{OVERSEA_BUNDLE_ID}.app"
    oversea.mkdir()
    bundle_id, app_path = resolve_playcover_bundle(CN_BUNDLE_ID, search_dirs=[apps])
    assert bundle_id == OVERSEA_BUNDLE_ID
    assert app_path == oversea

    cn = apps / f"{CN_BUNDLE_ID}.app"
    cn.mkdir()
    bundle_id2, app_path2 = resolve_playcover_bundle(CN_BUNDLE_ID, search_dirs=[apps])
    assert bundle_id2 == CN_BUNDLE_ID
    assert app_path2 == cn


def test_cg_client_activates_before_input_and_restores_focus(tmp_path):
    helper = tmp_path / "pc_helper"
    helper.write_text("#!/bin/sh\n")
    calls = []

    def fake_runner(cmd, capture_output=True, text=True, timeout=10.0):
        calls.append(cmd[1:])
        subcmd = cmd[1]
        if subcmd == "window-info":
            payload = {
                "ok": True,
                "frontmostBundleId": "com.apple.Terminal",
                "frontmostPid": 999,
                "screens": [{"x": 0, "y": 0, "width": 1728, "height": 1117, "scaleFactor": 2.0, "isMain": True}],
                "mainWindow": {
                    "wid": 42,
                    "pid": 123,
                    "owner": "崩坏:星穹铁道",
                    "title": "崩坏:星穹铁道",
                    "bundleId": CN_BUNDLE_ID,
                    "isActive": False,
                    "isHidden": False,
                    "bounds": {"x": 100.0, "y": 40.0, "width": 1280.0, "height": 744.0},
                },
            }
            return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps(payload), stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout=json.dumps({"ok": True, "action": subcmd}), stderr="")

    client = CGPlayCoverClient(bundle_id=CN_BUNDLE_ID, restore_focus=True, helper_path=helper, runner=fake_runner)
    client.click(960, 540)

    subcmds = [c[0] for c in calls]
    assert subcmds == ["window-info", "activate", "window-info", "click", "activate"]
    assert calls[1] == ["activate", "--pid", "123", "--wait-ms", "220"]
    assert calls[3][0] == "click"
    assert calls[4] == ["activate", "--pid", "999", "--wait-ms", "60"]

    # Without restore_focus, final reactivate of previous app is omitted
    calls.clear()
    client.restore_focus = False
    client.drag(100, 200, 400, 500, duration=0.3)
    assert [c[0] for c in calls] == ["window-info", "activate", "window-info", "drag"]


def test_cg_client_propagates_tcc_error_without_bypass(tmp_path):
    helper = tmp_path / "pc_helper"
    helper.write_text("#!/bin/sh\n")

    def fake_runner(cmd, capture_output=True, text=True, timeout=10.0):
        payload = {"ok": False, "error": "accessibility_denied", "message": "AXIsProcessTrusted() is false"}
        return subprocess.CompletedProcess(cmd, 2, stdout=json.dumps(payload), stderr="")

    client = CGPlayCoverClient(bundle_id=CN_BUNDLE_ID, helper_path=helper, runner=fake_runner)
    with pytest.raises(CGHelperError) as exc_info:
        client.tcc_check()
    assert exc_info.value.code == "accessibility_denied"


def test_playcover_controller_auto_transport_probe(monkeypatch):
    cfg = _DictConfig(playcover_transport="auto", playcover_bundle_id=CN_BUNDLE_ID, playcover_restore_focus=True)
    controller = PlayCoverGameController(cfg=cfg)

    monkeypatch.setattr(controller, "probe_maatools", Mock(return_value=True))
    assert controller.active_transport() == "maatools"

    monkeypatch.setattr(controller, "probe_maatools", Mock(return_value=False))
    assert controller.active_transport() == "cg"

    cfg.values["playcover_transport"] = "cg"
    monkeypatch.setattr(controller, "probe_maatools", Mock(return_value=True))
    assert controller.active_transport() == "cg"

    cfg.values["playcover_transport"] = "maatools"
    assert controller.active_transport() == "maatools"
