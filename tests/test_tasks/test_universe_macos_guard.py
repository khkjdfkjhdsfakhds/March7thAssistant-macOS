import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from module.config import cfg
from tasks.weekly import universe
from utils.tasks import WINDOWS_ONLY_TASKS, task_is_supported


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "method_name,args,expected_action",
    [
        ("update", (), "更新"),
        ("check_path", (), "路径检查"),
        ("check_requirements", (), "运行环境检查"),
        ("before_start", (), "启动准备"),
        ("start", (), "运行"),
        ("gui", (), "打开原版 GUI"),
    ],
)
def test_universe_methods_guard_non_windows_cleanly(
    monkeypatch, method_name, args, expected_action
):
    warnings = []
    monkeypatch.setattr(universe.sys, "platform", "darwin")
    monkeypatch.setattr(
        universe,
        "log",
        SimpleNamespace(
            hr=lambda *a, **k: None,
            info=lambda *a, **k: None,
            warning=lambda msg: warnings.append(msg),
            error=lambda *a, **k: None,
        ),
    )
    monkeypatch.setattr(
        universe,
        "subprocess_with_timeout",
        Mock(side_effect=AssertionError("must not spawn subprocess on macOS")),
    )
    monkeypatch.setattr(
        universe.subprocess,
        "run",
        Mock(side_effect=AssertionError("must not call subprocess.run on macOS")),
    )
    monkeypatch.setattr(
        universe,
        "pause_on_error",
        Mock(side_effect=AssertionError("must not pause_on_error on macOS")),
    )
    monkeypatch.setattr(
        universe,
        "pause_and_retry",
        Mock(side_effect=AssertionError("must not pause_and_retry on macOS")),
    )
    monkeypatch.setattr(
        universe.sys,
        "exit",
        Mock(side_effect=AssertionError("must not sys.exit on macOS")),
    )
    monkeypatch.setattr(
        universe,
        "cfg",
        SimpleNamespace(
            universe_count=1,
            universe_category="default",
            universe_path="/tmp/nonexistent-universe",
            universe_requirements=False,
            env={},
        ),
    )

    result = getattr(universe.Universe, method_name)(*args)

    assert result is False
    assert len(warnings) == 1
    assert expected_action in warnings[0]
    assert "差分宇宙" in warnings[0]
    assert "divergent" in warnings[0]


def test_windows_only_tasks_blocks_universe_family_on_darwin(monkeypatch):
    assert {"universe", "universe_gui", "universe_update"}.issubset(WINDOWS_ONLY_TASKS)
    desktop_cfg = SimpleNamespace(
        get_value=lambda key, default=None: {
            "playcover_enable": False,
            "cloud_game_enable": False,
        }.get(key, default)
    )
    monkeypatch.setattr(sys, "platform", "darwin")
    for task_id in ("universe", "universe_gui", "universe_update"):
        assert task_is_supported(task_id, desktop_cfg) is False
    for task_id in ("divergent", "divergentloop", "divergenttemp"):
        assert task_is_supported(task_id, desktop_cfg) is True

    monkeypatch.setattr(sys, "platform", "win32")
    for task_id in ("universe", "universe_gui", "universe_update"):
        assert task_is_supported(task_id, desktop_cfg) is True


def test_main_unsupported_universe_guard_precedes_run_action():
    source = (REPO_ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    main_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    fn_src = ast.get_source_segment(source, main_fn)
    assert fn_src is not None
    assert "task_is_supported" in fn_src
    assert fn_src.index("task_is_supported") < fn_src.index("_run_action")
    assert '"universe"' in fn_src and "divergent" in fn_src
    assert "unsupported_backend" in fn_src


@pytest.mark.skipif(sys.platform == "win32", reason="non-Windows pre-guard CLI test")
@pytest.mark.parametrize("task_id", ["universe", "universe_gui", "universe_update"])
def test_cli_universe_tasks_exit_fast_without_game_or_pause(tmp_path, task_id):
    cfg_text = (REPO_ROOT / "assets" / "config" / "config.example.yaml").read_text(encoding="utf-8")
    cfg_text = cfg_text.replace("playcover_enable: True", "playcover_enable: False")
    cfg_text = cfg_text.replace("playcover_transport: auto", "playcover_transport: cg")
    (tmp_path / "config.yaml").write_text(cfg_text, encoding="utf-8")
    env = os.environ.copy()
    env["M7A_FORCE_BUNDLE_MODE"] = "1"
    env["M7A_DATA_DIR"] = str(tmp_path)

    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "main.py"), task_id],
        cwd=str(REPO_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )

    assert proc.returncode == 1
    combined_output = proc.stdout + proc.stderr
    assert "差分宇宙" in combined_output
    assert "divergent" in combined_output
    assert "MaaTools" not in combined_output

    run_files = list((tmp_path / "logs" / "runs").glob("*.json"))
    assert run_files, "expected isolated RunSession log under tmp_path/logs/runs"
    session_data = json.loads(run_files[0].read_text(encoding="utf-8"))
    assert session_data["status"] == "blocked"
    assert session_data["reason"] == "unsupported_backend"
    assert "divergent" in (session_data.get("error") or "")
