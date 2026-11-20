import os
from pathlib import Path
import sys

import cv2
from PIL import Image
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from module.game.cg_client import crop_titlebar_and_resize_1080
from module.ocr import ocr
import tasks.weekly.currency_wars_ui as ui
from tasks.weekly.currency_wars import CurrencyWars
from tasks.weekly.currency_wars_ui import Frame, Page


_SHOTS_ENV = os.environ.get("M7A_PLAYCOVER_SHOTS_DIR", "").strip()
SHOTS_ROOT = Path(_SHOTS_ENV) if _SHOTS_ENV else Path("__missing_playcover_shots__")

if not _SHOTS_ENV or not SHOTS_ROOT.exists():
    pytest.skip(
        "Set M7A_PLAYCOVER_SHOTS_DIR to local PlayCover screenshot corpus to run frame OCR tests",
        allow_module_level=True,
    )


_FRAME_CACHE: dict[str, Frame] = {}


def load_real_frame(rel_path: str) -> Frame:
    """加载真实 PlayCover 截图（裁剪 24px 标题栏并缩放到 1920x1080），运行真实 RapidOCR 并解析 Frame。"""
    if rel_path in _FRAME_CACHE:
        return _FRAME_CACHE[rel_path]
    path = SHOTS_ROOT / rel_path
    assert path.is_file(), f"missing screenshot: {path}"
    raw_bgr = cv2.imread(str(path), cv2.IMREAD_COLOR)
    assert raw_bgr is not None
    assert raw_bgr.shape == (744, 1280, 3), f"expected 1280x744 window capture, got {raw_bgr.shape}"
    norm_bgr = crop_titlebar_and_resize_1080(raw_bgr, titlebar_pt=24.0, scale_factor=1.0)
    assert norm_bgr.shape == (1080, 1920, 3)
    rgb = Image.fromarray(cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2RGB))
    ocr_results = ocr.recognize_multi_lines(rgb)
    frame = Frame.from_ocr(rgb, ocr_results)
    _FRAME_CACHE[rel_path] = frame
    return frame


def _in_bounds(point: tuple[int, int]) -> bool:
    return 0 <= point[0] < 1920 and 0 <= point[1] < 1080


@pytest.mark.parametrize(
    ("rel_path", "expected_page"),
    (
        ("calib/002.jpg", Page.HOME),
        ("calib2/004.jpg", Page.HOME),
        ("calib2/146.jpg", Page.HOME),
        ("calib/011.jpg", Page.MODES),
        ("calib/014.jpg", Page.MODES),
        ("calib/004.jpg", Page.WEEKLY),
        ("calib/025.jpg", Page.RANK),
        ("calib2/008.jpg", Page.CONFIRM_FIGHT),
        ("calib2/157.jpg", Page.REWARD_RECEIPT),
        ("calib/049.jpg", Page.BATTLE),
        ("calib2/091.jpg", Page.BATTLE),
    ),
)
def test_playcover_menu_and_status_pages(rel_path: str, expected_page: Page):
    frame = load_real_frame(rel_path)
    assert frame.page == expected_page


def test_playcover_weekly_and_confirm_details():
    weekly = load_real_frame("calib/004.jpg")
    assert weekly.page == Page.WEEKLY
    assert weekly.mobile_layout is True
    assert weekly.ratio(ui.WEEKLY_SCORE) == (18000, 18000)
    assert weekly.claim_available() is False

    confirm = load_real_frame("calib2/008.jpg")
    assert confirm.page == Page.CONFIRM_FIGHT
    btn = confirm.find("确认")
    assert btn is not None and _in_bounds(btn.point)

    modes = load_real_frame("calib/014.jpg")
    entry = modes.find(*ui.MODE_ENTRIES, *ui.CONTINUE_MATCH)
    assert entry is not None and _in_bounds(entry.point)


@pytest.mark.parametrize(
    ("rel_path", "expected_kind", "expected_btn"),
    (
        ("calib/031.jpg", "开局预览", "下一步"),
        ("calib/032.jpg", "位面预览", "点击空白处继续"),
        ("calib/035.jpg", "奇遇说明", "点击空白处继续"),
        ("calib2/058.jpg", "节点说明", "点击空白处继续"),
    ),
)
def test_playcover_reveal_pages(rel_path: str, expected_kind: str, expected_btn: str):
    frame = load_real_frame(rel_path)
    assert frame.page == Page.REVEAL
    assert frame.reveal_kind == expected_kind
    btn = frame.reveal_button()
    assert btn is not None and btn.text == expected_btn
    assert _in_bounds(btn.point)


def test_playcover_board_early_mid_late():
    early = load_real_frame("calib/036.jpg")
    assert early.page == Page.BOARD
    assert early.mobile_layout is True
    assert early.capacity == (0, 3)
    assert early.squad_health == 100
    assert early.gold == 5
    assert early.level == 3
    assert early.experience == (0, 4)
    assert early.experience_cost == 4
    early_slots = early.slots()
    assert len(early_slots) == 19
    assert sum(slot.occupied for slot in early_slots) == 4
    assert len(early.inventory_items()) == 1
    assert early.find("商店", area=ui.BOARD_SHOP) is not None
    assert early.find(*ui.BOARD_ADVANCE, area=ui.BOARD_FIGHT) is not None

    six_back = load_real_frame("calib/046.jpg")
    assert six_back.page == Page.BOARD
    assert six_back.capacity == (4, 4)
    assert six_back.back_row() == (582, 734, 884, 1036, 1186, 1338)
    assert sum(slot.occupied for slot in six_back.slots()) == 5

    mid = load_real_frame("calib2/033.jpg")
    assert mid.page == Page.BOARD
    assert mid.capacity == (5, 6)
    assert mid.gold == 9
    assert mid.level == 6
    assert mid.experience == (0, 36)
    assert len(mid.inventory_items()) == 2
    mid_occ = [slot for slot in mid.slots() if slot.occupied]
    assert [mid.card_stars(slot) for slot in mid_occ[:3]] == [2, 1, 1]
    assert all(any(mid.card_role(slot)) for slot in mid_occ)

    late = load_real_frame("calib2/137.jpg")
    assert late.page == Page.BOARD
    assert late.capacity == (9, 9)
    assert late.gold == 18
    assert late.level == 9
    assert late.experience == (24, 72)
    assert len(late.inventory_items()) == 3
    late_occ = [slot for slot in late.slots() if slot.occupied]
    assert len(late_occ) == 13
    assert any(late.card_role(slot) == (True, False) for slot in late_occ)


def test_playcover_shop_pages():
    base = load_real_frame("calib/043.jpg")
    assert base.page == Page.SHOP
    assert base.mobile_layout is True
    assert [(o.name, o.cost, o.front, o.back) for o in base.offers] == [
        ("刻律德菈", 1, False, True),
        ("桂乃芬", 1, True, True),
        ("三月七", 1, False, True),
        ("三月七", 1, False, True),
        ("波提欧", 1, True, False),
    ]
    assert [o.point for o in base.offers] == [(365, 220), (701, 220), (1037, 220), (1373, 220), (1709, 220)]

    purple_4cost = load_real_frame("calib2/126.jpg")
    assert purple_4cost.page == Page.SHOP
    assert [(o.name, o.cost) for o in purple_4cost.offers] == [
        ("爻光", 3),
        ("流萤", 2),
        ("寒鸦", 4),
        ("希露瓦", 4),
        ("镜流", 3),
    ]

    shifted = load_real_frame("calib2/131.jpg")
    assert shifted.page == Page.SHOP
    assert [(o.name, o.cost) for o in shifted.offers] == [
        ("砂金·戏浪", 4),
        ("真珠", 1),
        ("赛飞儿", 3),
        ("椒丘", 3),
    ]

    five_cost = load_real_frame("calib2/136.jpg")
    assert five_cost.page == Page.SHOP
    assert [(o.name, o.cost) for o in five_cost.offers] == [
        ("长夜月", 1),
        ("赛飞儿", 3),
        ("阿格莱雅", 5),
        ("银狼LV.999", 3),
        ("雪衣", 5),
    ]


def test_playcover_choice_and_event_pages():
    env = load_real_frame("calib/033.jpg")
    assert env.page == Page.CHOICE
    assert env.mobile_layout is True
    assert env.choice == "投资环境"
    assert env.investment_centers == (384, 960, 1538)
    assert env.investment_titles() == ("奇兽花园概念股", "连击概念股", "火药味")
    assert env.uncollected_investment_columns == frozenset({0, 2})
    assert env.selected_investment_column() is None

    strat1 = load_real_frame("calib2/017.jpg")
    assert strat1.page == Page.CHOICE
    assert strat1.mobile_layout is True
    assert strat1.choice == "请选择投资策略"
    assert strat1.investment_centers == (402, 960, 1518)
    assert strat1.investment_titles() == ("气氛组", "公司军火更新·银", "招聘资金")
    assert strat1.uncollected_investment_columns == frozenset({0, 1, 2})
    assert [strat1.investment_refresh_count(i) for i in range(3)] == [1, 1, 1]
    assert strat1.investment_refresh_points == ((315, 880), (872, 880), (1432, 880))

    strat2 = load_real_frame("calib2/076.jpg")
    assert strat2.page == Page.CHOICE
    assert strat2.mobile_layout is True
    assert strat2.choice == "请选择投资策略"
    assert strat2.investment_titles() == ("蓝钻闪耀", "打人就打脸·金", "折叠小刀祝福")
    assert strat2.uncollected_investment_columns == frozenset({0, 1, 2})
    assert [strat2.investment_refresh_count(i) for i in range(3)] == [1, 1, 1]
    assert strat2.investment_refresh_points == ((314, 897), (872, 897), (1429, 897))

    strat3 = load_real_frame("calib2/110.jpg")
    assert strat3.page == Page.CHOICE
    assert strat3.mobile_layout is True
    assert strat3.choice == "请选择投资策略"
    assert strat3.investment_titles() == ("这么大的钻石", "人才大礼包++", "回收计划+")
    assert [strat3.investment_refresh_count(i) for i in range(3)] == [1, 1, 1]
    assert strat3.investment_refresh_points == ((315, 880), (872, 880), (1432, 880))

    recruit = load_real_frame("calib2/020.jpg")
    assert recruit.page == Page.CHOICE
    assert recruit.choice == "3费聘用书"
    recruit_names = [label.text for label in recruit.recruitment_cards]
    assert {"乱破", "椒丘", "大丽花"}.issubset(recruit_names)

    supply = load_real_frame("calib2/081.jpg")
    assert supply.page == Page.CHOICE
    assert supply.mobile_layout is True
    assert supply.choice == "补给阶段"
    assert supply.supply_centers == ui.MOBILE_SUPPLY_CENTERS
    assert [(lbl.text, eq, front) for lbl, eq, front in supply.supply_cards()] == [
        ("缇宝", "折叠小刀", True),
        ("遐蝶", "量产型装甲", True),
        ("花火", "以太钻头", True),
        ("银狼LV.999", "幸运星", True),
        ("三月七", "轮滑鞋", False),
    ]

    garden = load_real_frame("calib/040.jpg")
    assert garden.page == Page.GARDEN
    assert garden.mobile_layout is True
    assert garden.board_effect_columns == ui.MOBILE_GARDEN_COLUMNS
    assert garden.board_effect_waiting is True
    assert garden.board_effect_selected == ()
    assert [lbl.text for lbl, _ in garden.board_effect_cards] == ["画饼王", "努努斯", "奇美拉投影仪"]

    dance = load_real_frame("calib2/023.jpg")
    assert dance.page == Page.DANCE
    assert dance.mobile_layout is True
    assert [lbl.text for lbl in dance.employee_event_candidates] == ["长夜月", "大丽花"]
    assert dance.employee_event_selected == frozenset()

    dance_selected = load_real_frame("calib2/024.jpg")
    assert dance_selected.page == Page.DANCE
    assert dance_selected.mobile_layout is True
    assert dance_selected.employee_event_selected == frozenset({"长夜月"})


def test_playcover_results_halo_and_tea():
    node = load_real_frame("calib/051.jpg")
    assert node.page == Page.NODE_RESULT
    assert node.result_heading == "挑战成功"
    assert node.result_buttons((0, 0, 1920, 1080)) == ("继续挑战",)

    node_final = load_real_frame("calib2/141.jpg")
    assert node_final.page == Page.NODE_RESULT
    assert node_final.result_heading == "挑战成功"
    assert node_final.result_buttons((0, 0, 1920, 1080)) == ("前往结算",)

    match1 = load_real_frame("calib2/143.jpg")
    assert match1.page == Page.MATCH_RESULT
    assert match1.result_heading == "对局评价|挑战成功"
    assert match1.result_buttons((0, 0, 1920, 1080)) == ("下一步",)

    match2 = load_real_frame("calib2/144.jpg")
    assert match2.page == Page.MATCH_RESULT
    assert match2.result_heading == "对局胜利"
    assert match2.result_buttons((0, 0, 1920, 1080)) == ("下一页",)

    halo_board = load_real_frame("calib2/060.jpg")
    front_occupied = [s for s in halo_board.slots() if s.zone == "front" and s.occupied]
    halo_empty = load_real_frame("calib2/062.jpg")
    assert halo_empty.page == Page.HALO
    assert halo_empty.halo_front == ui.MOBILE_HALO_FRONT
    assert [halo_empty.halo_title(i) for i in range(2)] == ["灵魂打击者", "双数跃迁"]
    assert halo_empty.halo_gold == 5
    assert [halo_empty.halo_effect_selected(i) for i in range(2)] == [False, False]
    assert halo_empty.halo_target_present() is False
    assert [
        halo_empty.halo_portrait_matches(
            halo_empty.halo_front[s.index],
            cv2.resize(halo_board.slot_mark(s.point), (12, 12)),
        )
        for s in front_occupied[1:]
    ] == [True, True, True]

    halo_ready = load_real_frame("calib2/066.jpg")
    assert halo_ready.page == Page.HALO
    assert [halo_ready.halo_title(i) for i in range(2)] == ["灵魂打击者", "双数跃迁"]
    assert halo_ready.halo_gold == 5
    assert [halo_ready.halo_effect_selected(i) for i in range(2)] == [False, True]
    assert halo_ready.halo_target_present() is True

    tea_shake = load_real_frame("calib2/048.jpg")
    assert tea_shake.page == Page.TEA
    assert tea_shake.tea_hp == 100
    assert tea_shake.tea_button().text == "摇一摇"

    tea_meal = load_real_frame("calib2/054.jpg")
    assert tea_meal.page == Page.TEA
    assert tea_meal.tea_hp == 100
    assert tea_meal.tea_button().text == "美餐时间"


def test_playcover_rank_pages():
    high = load_real_frame("calib/025.jpg")
    assert high.page == Page.RANK
    assert high.mobile_layout is True
    assert high.rank_tier == 4
    assert high.enemy_rank == 23
    assert high.rank_affixes == 2
    assert high.match("screen/currency_wars/level_down.png", ui.RANK_DOWN) == (960, 815)
    assert high.find("返回最高职级", area=ui.RANK_RETURN) is None

    mid = load_real_frame("calib/027.jpg")
    assert mid.page == Page.RANK
    assert mid.mobile_layout is True
    assert mid.rank_tier == 2
    assert mid.enemy_rank == 12
    assert mid.rank_affixes == 1
    assert mid.match("screen/currency_wars/level_down.png", ui.RANK_DOWN) == (960, 815)
    ret_mid = mid.find("返回最高职级", area=ui.RANK_RETURN)
    assert ret_mid is not None and _in_bounds(ret_mid.point)

    low = load_real_frame("calib/029.jpg")
    assert low.page == Page.RANK
    assert low.mobile_layout is True
    assert low.rank_tier == 0
    assert low.enemy_rank == 1
    assert low.rank_affixes == 0
    assert low.match("screen/currency_wars/level_down.png", ui.RANK_DOWN) is None
    ret_low = low.find("返回最高职级", area=ui.RANK_RETURN)
    assert ret_low is not None and _in_bounds(ret_low.point)


@pytest.mark.parametrize(
    ("rel_path", "expected_mobile", "expected_auto_off", "expected_toggle"),
    (
        ("calib/049.jpg", True, True, (1725, 58)),
        ("calib2/014.jpg", True, True, (1725, 58)),
        ("calib2/114.jpg", True, False, (1725, 58)),
        ("calib2/101.jpg", True, False, (1725, 58)),
        ("calib2/091.jpg", False, False, ui.AUTO_TOGGLE),
    ),
)
def test_playcover_battle_auto_toggle(
    rel_path: str,
    expected_mobile: bool,
    expected_auto_off: bool,
    expected_toggle: tuple[int, int],
):
    frame = load_real_frame(rel_path)
    assert frame.page == Page.BATTLE
    assert frame.mobile_layout is expected_mobile
    assert frame.auto_off is expected_auto_off
    assert frame.auto_toggle == expected_toggle


def test_playcover_board_disassembly_tool():
    for rel_path in ("calib2/009.jpg", "calib2/137.jpg"):
        board = load_real_frame(rel_path)
        assert board.page == Page.BOARD
        assert board.mobile_layout is True
        tool = board.disassembly_tool()
        assert tool == (1826, 178) and _in_bounds(tool)

    # Mask top-right equipment slot on BOARD to verify negative case without wrench icon.
    sample = load_real_frame("calib2/009.jpg")
    masked = sample.pixels.copy()
    masked[111:260, 1540:1900] = 0
    no_wrench = Frame(Image.fromarray(masked), sample.labels)
    assert no_wrench.page == Page.BOARD
    assert no_wrench.mobile_layout is True
    assert no_wrench.disassembly_tool() is None


def _run_frame_action(monkeypatch, frame: Frame, after: Frame, runner, *, advance_on=None):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tasks.weekly.currency_wars as cw_task

    now = [0.0]
    cfg = SimpleNamespace(
        currencywars_type="normal",
        currencywars_rank_difficulty="current",
        currencywars_fast_mode=False,
        currencywars_bonus_enable=False,
        currencywars_strategy="s2_anaxa_high",
        save_timestamp=Mock(),
        currencywars_timestamp=1,
        refresh_hour=4,
    )
    cfg.get_value = lambda key, default=None: getattr(cfg, key, default)
    fake_auto = Mock()
    fake_auto.find_element.side_effect = lambda target, *args, **kwargs: tuple(
        round(value * scale) for value, scale in zip(target[:2], (1920, 1080))
    )
    clicks = []
    state = {"frame": frame}

    def click(point, *, press_duration):
        clicks.append((state["frame"].page, point))
        if advance_on is None or advance_on(point):
            state["frame"] = after
        return True

    fake_auto.click_element_with_pos.side_effect = click
    monkeypatch.setattr(cw_task, "cfg", cfg)
    monkeypatch.setattr(cw_task, "auto", fake_auto)
    monkeypatch.setattr(cw_task, "get_ui_profile", lambda _: SimpleNamespace(name="pc_1080"))
    monkeypatch.setattr(cw_task, "pause_ctl", Mock())
    monkeypatch.setattr(cw_task, "Base", Mock())
    monkeypatch.setattr(cw_task, "save_error_screenshot", Mock())
    monkeypatch.setattr(
        cw_task,
        "time",
        SimpleNamespace(monotonic=lambda: now[0], time=lambda: 1794405000, sleep=lambda s: now.__setitem__(0, now[0] + s)),
    )
    war = cw_task.CurrencyWars()
    war.mode = "normal"
    war.frame = frame

    def observe():
        war.frame = state["frame"]
        return state["frame"]

    monkeypatch.setattr(war, "_observe", observe)
    result = runner(war, frame)
    return result, clicks


def _run_preselected_choose(monkeypatch, frame: Frame, after: Frame):
    return _run_frame_action(monkeypatch, frame, after, lambda war, f: war._choose(f), advance_on=lambda pt: pt[1] >= 900)


def test_playcover_preselected_investment_recovery(monkeypatch):
    base = load_real_frame("calib2/076.jpg")
    pixels = base.pixels.copy()
    # 076 金卡外框位于 402 ± 211，选中白边落在 ±216..226，而非 ±190..200。
    pixels[405:755, 176:186] = 210
    pixels[405:755, 618:628] = 210
    pixels[970:1005, 920:1045] = 220
    frame = Frame(Image.fromarray(pixels), base.labels)
    assert frame.page == Page.CHOICE
    assert frame.mobile_layout is True
    assert frame.selected_investment_column() == 0
    assert frame.choice_selected(frame, (402, 500)) is True
    assert frame.choice_confirm() is not None

    after = load_real_frame("calib2/009.jpg")
    result, clicks = _run_preselected_choose(monkeypatch, frame, after)
    assert result is after
    assert clicks == [(Page.CHOICE, (1518, 569)), (Page.CHOICE, (984, 987))]

    wide_base = load_real_frame("calib2/017.jpg")
    wide_px = wide_base.pixels.copy()
    # 017 常规宽策略卡外框位于 402 ± 224，选中外描边落在 ±230..240。
    wide_px[405:755, 165:173] = 215
    wide_px[405:755, 631:639] = 215
    wide_px[970:1005, 920:1045] = 220
    wide_frame = Frame(Image.fromarray(wide_px), wide_base.labels)
    assert wide_frame.selected_investment_column() == 0
    assert wide_frame.choice_selected(wide_frame, (402, 500)) is True


def test_playcover_investment_env_wide_outline_and_real_error_recovery(monkeypatch):
    env_base = load_real_frame("calib/033.jpg")
    pixels = env_base.pixels.copy()
    pixels[201:899, 703:707] = 250
    pixels[201:899, 1214:1219] = 250
    pixels[970:1005, 920:1045] = 220
    synth = Frame(Image.fromarray(pixels), env_base.labels)
    assert synth.page == Page.CHOICE
    assert synth.choice == "投资环境"
    assert synth.mobile_layout is True
    assert synth.selected_investment_column() == 1
    assert synth.choice_selected(synth, (960, 400)) is True

    after = load_real_frame("calib2/009.jpg")
    result, clicks = _run_preselected_choose(monkeypatch, synth, after)
    assert result is after
    assert clicks == [(Page.CHOICE, (960, 383)), (Page.CHOICE, (960, 987))]

    err_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-15_18-11-26.png"
    if err_path.is_file():
        bgr = cv2.imread(str(err_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        real_err = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb))
        assert real_err.page == Page.CHOICE
        assert real_err.choice == "投资环境"
        assert real_err.mobile_layout is True
        assert real_err.selected_investment_column() == 1
        confirm = real_err.choice_confirm()
        assert confirm is not None and confirm.point == (1114, 986)
        assert real_err.choice_selected(real_err, (960, 400)) is True
        result, clicks = _run_preselected_choose(monkeypatch, real_err, after)
        assert result is after
        assert len(clicks) == 2 and clicks[0][0] == Page.CHOICE and clicks[0][1][1] < 900
        assert clicks[1] == (Page.CHOICE, (1114, 986))


def test_playcover_pause_confirm_real_error_recovery(monkeypatch):
    import tasks.weekly.currency_wars_ui as ui

    after = load_real_frame("calib2/009.jpg")
    synth_labels = (
        ui.Label("提示", (734, 292)),
        ui.Label("是否中断挑战并保存当前进度？进度将保留至1-1。", (1028, 380)),
        ui.Label("放弃并结算", (722, 794)),
        ui.Label("暂时离开", (1246, 794)),
    )
    synth = Frame(Image.new("RGB", (1920, 1080), (40, 40, 40)), synth_labels)
    assert synth.page == Page.PAUSE_CONFIRM
    assert synth.mobile_layout is False
    assert synth.pause_close() == ui.PAUSE_CLOSE == (1587, 292)
    result, clicks = _run_frame_action(monkeypatch, synth, after, lambda war, f: war._play_step(f))
    assert result is after
    assert clicks == [(Page.PAUSE_CONFIRM, (1587, 292))]

    err_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-15_18-45-04.png"
    if err_path.is_file():
        bgr = cv2.imread(str(err_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        real_err = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb))
        assert real_err.page == Page.PAUSE_CONFIRM
        assert real_err.pause_close() == (1587, 292)
        result, clicks = _run_frame_action(monkeypatch, real_err, after, lambda war, f: war._play_step(f))
        assert result is after
        assert clicks == [(Page.PAUSE_CONFIRM, (1587, 292))]


def test_playcover_mobile_detail_and_equipment_regression(monkeypatch):
    import tasks.weekly.currency_wars_ui as ui

    after = load_real_frame("calib2/009.jpg")
    err_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-15_19-06-23.png"
    if err_path.is_file():
        bgr = cv2.imread(str(err_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        real_detail = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb))
        assert real_detail.page == Page.DETAIL
        assert real_detail.mobile_layout is True
        assert real_detail.stage == "1-2"
        assert real_detail.employee_name(local=True) == "罗刹"
        assert real_detail.employee_output(allow_dual=True) is False
        assert real_detail.sell_price == 3
        assert real_detail.equipment_full() is False
        recommend = real_detail.find(*ui.DETAIL_RECOMMEND, area=real_detail.detail_equip_area)
        assert recommend is not None and recommend.point == (1409, 861)
        sell_btn = real_detail.find("出售", area=real_detail.detail_sell_area)
        assert sell_btn is not None and sell_btn.point == (1734, 984)
        result, clicks = _run_frame_action(monkeypatch, real_detail, after, lambda war, f: war._play_step(f))
        assert result is after
        assert clicks == [(Page.DETAIL, (680, 165))]


def test_playcover_mobile_item_box_real_error_recovery(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    from PIL import ImageDraw
    import tasks.weekly.currency_wars as cw

    supply = load_real_frame("calib2/081.jpg")
    assert supply.item_cards() == ()

    err_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-15_19-48-16.png"
    if err_path.is_file():
        bgr = cv2.imread(str(err_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        real_err = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb))
        assert real_err.page == Page.CHOICE
        assert real_err.mobile_layout is True
        assert real_err.stage == "3-5"
        assert real_err.choice == "简易武装箱"
        assert [c.text for c in real_err.item_cards()] == ["以太钻头", "幸运星", "折叠小刀", "轮滑鞋"]
        assert cw.CurrencyWars._choice_box_slots(real_err) == ((932, 897),)

        board_img = rgb.copy()
        ImageDraw.Draw(board_img).rectangle((892, 857, 972, 937), fill=(35, 30, 74))
        board_labels = (
            ui.Label("备战阶段", (143, 60)),
            ui.Label("3-5", (144, 108)),
            ui.Label("6/10", (960, 250)),
            ui.Label("前台区域", (960, 307)),
            ui.Label("后台区域", (960, 577)),
            ui.Label("出战", (1793, 722)),
            ui.Label("商店", (1789, 984)),
        )
        board_after = Frame(board_img, board_labels)
        assert board_after.page == Page.BOARD
        assert board_after.mobile_layout is True

        now = [0.0]
        monkeypatch.setattr(cw, "cfg", SimpleNamespace(currencywars_strategy="s2_anaxa_high", get_value=lambda _k, d=None: d))
        monkeypatch.setattr(cw, "auto", Mock())
        monkeypatch.setattr(cw, "get_ui_profile", lambda _: SimpleNamespace(name="mobile_1080"))
        monkeypatch.setattr(cw, "pause_ctl", Mock())
        monkeypatch.setattr(cw, "Base", Mock())
        monkeypatch.setattr(cw, "save_error_screenshot", Mock())
        monkeypatch.setattr(cw, "time", SimpleNamespace(
            monotonic=lambda: now[0],
            time=lambda: 1794405000,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
        ))

        war = cw.CurrencyWars()
        state = SimpleNamespace(frame=real_err)
        clicks = []
        monkeypatch.setattr(war, "_capture", lambda: state.frame)

        def fake_tap(frame, point):
            clicks.append((frame.page, point))
            if point == (1591, 392):
                state.frame = board_after
            return board_after

        monkeypatch.setattr(war, "_tap", fake_tap)
        result = war._choose(real_err)
        assert result is board_after
        assert clicks == [(Page.CHOICE, (1591, 392))]


def test_playcover_mobile_battle_auto_off_warm_bg_regression(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tasks.weekly.currency_wars as cw

    for rel in ("calib2/079.jpg", "calib2/139.jpg", "calib2/140.jpg"):
        on_frame = load_real_frame(rel)
        assert on_frame.page == Page.BATTLE
        assert on_frame.mobile_layout is True
        assert on_frame.auto_off is False

    probe_path = SHOTS_ROOT / "probe_run2_stall.png"
    if probe_path.is_file():
        raw_bgr = cv2.imread(str(probe_path), cv2.IMREAD_COLOR)
        assert raw_bgr is not None and raw_bgr.shape == (744, 1280, 3)
        norm_bgr = crop_titlebar_and_resize_1080(raw_bgr, titlebar_pt=24.0, scale_factor=1.0)
        rgb = Image.fromarray(cv2.cvtColor(norm_bgr, cv2.COLOR_BGR2RGB))
        probe = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb))
        assert probe.page == Page.BATTLE
        assert probe.mobile_layout is True
        assert probe.stage == "1-1"
        assert probe.auto_off is True
        assert probe.auto_toggle == ui.MOBILE_AUTO_TOGGLE

        on_frame = load_real_frame("calib2/114.jpg")
        end_frame = Frame(probe.pixels, (ui.Label("战斗胜利", (960, 160)), ui.Label("下一页", (960, 960))))
        end_frame.__dict__["page"] = Page.NODE_RESULT

        now = [0.0]
        monkeypatch.setattr(cw, "cfg", SimpleNamespace(auto_battle_detect_enable=True, get_value=lambda _k, d=None: d))
        monkeypatch.setattr(cw, "auto", Mock())
        monkeypatch.setattr(cw, "get_ui_profile", lambda _: SimpleNamespace(name="pc_1080"))
        monkeypatch.setattr(cw, "pause_ctl", Mock())
        monkeypatch.setattr(cw, "Base", Mock())
        monkeypatch.setattr(cw, "save_error_screenshot", Mock())
        monkeypatch.setattr(cw, "time", SimpleNamespace(
            monotonic=lambda: now[0],
            time=lambda: 1794405000,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
        ))

        war = cw.CurrencyWars()
        seq = iter((probe, on_frame, on_frame, end_frame))
        clicks = []
        monkeypatch.setattr(war, "_observe", lambda: next(seq))
        monkeypatch.setattr(war, "_tap", lambda f, pt, **kw: clicks.append((f.page, pt)) or on_frame)

        assert war._watch_battle(probe) is end_frame
        assert clicks == [(Page.BATTLE, (1725, 58))]


def test_playcover_mobile_compact_detail_and_dance_followup(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tasks.weekly.currency_wars as cw

    halo_preview = load_real_frame("calib2/065.jpg")
    assert halo_preview.page == Page.HALO
    assert halo_preview.mobile_layout is True
    assert halo_preview.employee_name() == "万敌"
    assert halo_preview.employee_output(allow_dual=True) is True
    assert halo_preview._mobile_equip_row_y() == 934

    err_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-15_20-24-39.png"
    if err_path.is_file():
        bgr = cv2.imread(str(err_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        compact_detail = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb))
        assert compact_detail.page == Page.DETAIL
        assert compact_detail.mobile_layout is True
        assert compact_detail.stage == "1-2"
        assert compact_detail.employee_name() == "黑天鹅"
        assert compact_detail.employee_output(allow_dual=True) is True
        rec = compact_detail.find(*ui.DETAIL_RECOMMEND, area=compact_detail.detail_equip_area)
        assert rec is not None and rec.point[1] >= 900
        assert compact_detail._mobile_equip_row_y() == 934
        assert compact_detail.equipment_full() is False

        board_after = load_real_frame("calib2/009.jpg")
        now = [0.0]
        monkeypatch.setattr(cw, "cfg", SimpleNamespace(get_value=lambda _k, d=None: d))
        monkeypatch.setattr(cw, "auto", Mock())
        monkeypatch.setattr(cw, "get_ui_profile", lambda _: SimpleNamespace(name="pc_1080"))
        monkeypatch.setattr(cw, "pause_ctl", Mock())
        monkeypatch.setattr(cw, "Base", Mock())
        monkeypatch.setattr(cw, "save_error_screenshot", Mock())
        monkeypatch.setattr(cw, "time", SimpleNamespace(
            monotonic=lambda: now[0],
            time=lambda: 1794405000,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
        ))

        war = cw.CurrencyWars()
        war.mobile_layout = True
        state = SimpleNamespace(frame=compact_detail)
        clicks = []
        monkeypatch.setattr(war, "_capture", lambda: state.frame)

        def fake_tap(frame, point, **_kw):
            clicks.append((frame.page, point))
            if point == (680, 165):
                state.frame = board_after
            return board_after

        monkeypatch.setattr(war, "_tap", fake_tap)
        assert war._close_detail(compact_detail) is board_after
        assert clicks == [(Page.DETAIL, (680, 165))]


def test_playcover_mobile_shop_3_4_does_not_false_trigger_conflict(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tasks.weekly.currency_wars as cw

    for rel, expected_stage in (("calib2/018.jpg", "1-3"), ("calib2/072.jpg", "2-1"), ("calib2/090.jpg", "2-6")):
        shop = load_real_frame(rel)
        assert shop.page == Page.SHOP
        assert shop.mobile_layout is True
        assert shop.stage == expected_stage
        assert shop.combat_buttons is False
        assert shop._mobile_auto_pill() is None

    err_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-15_21-15-40.png"
    if err_path.is_file():
        bgr = cv2.imread(str(err_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        shop_3_4 = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert shop_3_4.mobile_layout is True
        assert shop_3_4._mobile_battle_ping is False
        assert shop_3_4._mobile_auto_pill() is None
        assert shop_3_4.combat_buttons is False
        assert shop_3_4.page == Page.SHOP
        assert shop_3_4.stage == "3-4"
        assert shop_3_4.gold == 60
        assert shop_3_4.shop_open is True
        assert [offer.name for offer in shop_3_4.offers] == ["赛飞儿", "知更鸟·晴歌", "白露", "景元", "缇宝"]

        board_after = load_real_frame("calib2/009.jpg")
        now = [0.0]
        monkeypatch.setattr(cw, "cfg", SimpleNamespace(get_value=lambda _k, d=None: d))
        monkeypatch.setattr(cw, "auto", Mock())
        monkeypatch.setattr(cw, "get_ui_profile", lambda _: SimpleNamespace(name="pc_1080"))
        monkeypatch.setattr(cw, "pause_ctl", Mock())
        monkeypatch.setattr(cw, "Base", Mock())
        monkeypatch.setattr(cw, "save_error_screenshot", Mock())
        monkeypatch.setattr(cw, "time", SimpleNamespace(
            monotonic=lambda: now[0],
            time=lambda: 1794405000,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
        ))

        war = cw.CurrencyWars()
        state = SimpleNamespace(frame=shop_3_4)
        clicks = []
        monkeypatch.setattr(war, "_capture", lambda: state.frame)

        def fake_tap(frame, point, **_kw):
            clicks.append((frame.page, point))
            if point == (1788, 985):
                state.frame = board_after
            return board_after

        monkeypatch.setattr(war, "_tap", fake_tap)
        assert war._close_shop(shop_3_4) is board_after
        assert clicks == [(Page.SHOP, (1788, 985))]


def test_playcover_bench_full_2_3_and_mobile_detail_name_recovery(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tasks.weekly.currency_wars as cw

    shot_dir = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots"
    bench_full_path = shot_dir / "error_2026-11-15_23-55-10.png"
    if bench_full_path.is_file():
        bgr = cv2.imread(str(bench_full_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        bench_full = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert bench_full.mobile_layout is True
        assert bench_full.page == Page.BENCH_FULL
        assert bench_full.shop_open is True
        boxes = [label for label in bench_full.texts(bench_full.bench_box_area) if label.text == "开启"]
        assert len(boxes) == 1 and boxes[0].point[0] > 1500

        board_after = load_real_frame("calib2/009.jpg")
        now = [0.0]
        monkeypatch.setattr(cw, "cfg", SimpleNamespace(get_value=lambda _k, d=None: d))
        monkeypatch.setattr(cw, "auto", Mock())
        monkeypatch.setattr(cw, "get_ui_profile", lambda _: SimpleNamespace(name="pc_1080"))
        monkeypatch.setattr(cw, "pause_ctl", Mock())
        monkeypatch.setattr(cw, "Base", Mock())
        monkeypatch.setattr(cw, "save_error_screenshot", Mock())
        monkeypatch.setattr(cw, "time", SimpleNamespace(
            monotonic=lambda: now[0],
            time=lambda: 1794405000,
            sleep=lambda s: now.__setitem__(0, now[0] + s),
        ))

        war = cw.CurrencyWars()
        monkeypatch.setattr(war, "_settle_board", lambda f: f)
        state = SimpleNamespace(frame=bench_full)
        clicks = []
        monkeypatch.setattr(war, "_capture", lambda: state.frame)

        def fake_tap(frame, point, **_kw):
            clicks.append((frame.page, point))
            if point == (1788, 985):
                state.frame = board_after
            return board_after

        monkeypatch.setattr(war, "_tap", fake_tap)
        assert war._free_reward_slot(bench_full) is board_after
        assert clicks == [(Page.BENCH_FULL, (1788, 985))]

    for fname, expected in (("error_2026-11-15_19-06-23.png", "罗刹"),
                            ("error_2026-11-15_20-24-39.png", "黑天鹅")):
        p = shot_dir / fname
        if p.is_file():
            bgr = cv2.imread(str(p), cv2.IMREAD_COLOR)
            rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            full_frame = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
            stripped = Frame(
                rgb,
                tuple(label for label in full_frame.labels
                      if label.text not in ("前台", "后台", "前后台", expected)),
            )
            assert stripped.mobile_layout is True
            assert stripped.employee_name(local=True) == expected


def test_playcover_halo_assigned_and_mobile_halo_detail():
    board_halo = load_real_frame("calib2/098.jpg")
    assert board_halo.mobile_layout is True
    assert board_halo.assigned_halo((732, 397)) is True
    assert [board_halo.assigned_halo((x, 397)) for x in (883, 1034, 1185)] == [False, False, False]

    err_halo_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-16_00-52-10.png"
    if err_halo_path.is_file():
        bgr = cv2.imread(str(err_halo_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        halo_detail = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert halo_detail.mobile_layout is True
        assert halo_detail.page == Page.HALO_DETAIL
        assert halo_detail.halo_detail_name_matches("那刻夏") is True
        assert halo_detail.halo_detail_name_matches("知更鸟") is False


def test_playcover_partner_detail_3_3_and_mobile_card_equipment_and_orbs(monkeypatch):
    early = load_real_frame("calib/036.jpg")
    assert [early.card_equipment(s) for s in early.bench_slots()[:4]] == [0, 0, 0, 0]

    halo_board = load_real_frame("calib2/098.jpg")
    assert [halo_board.card_equipment(s) for s in halo_board.slots() if s.zone == "front"] == [1, 1, 2, 1]
    assert len(halo_board.reward_orbs()) > 0

    late = load_real_frame("calib2/137.jpg")
    assert [late.card_equipment(s) for s in late.slots() if s.zone == "front"] == [0, 1, 2, 3]
    assert late.card_equipment(late.bench_slots()[3]) == 0
    assert len(late.reward_orbs()) > 0

    err_partner_path = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-16_01-46-12.png"
    if err_partner_path.is_file():
        bgr = cv2.imread(str(err_partner_path), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        partner = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert partner.mobile_layout is True
        assert partner.page == Page.PARTNER_DETAIL
        assert partner.stage == "3-3"
        assert partner.reward_orbs() == ()
        assert [partner.card_equipment(s) for s in partner.bench_slots()] == [0, 0, 0, 0, 0, 0, 1, 0, 0]

        board_after = load_real_frame("calib2/009.jpg")
        result, clicks = _run_frame_action(monkeypatch, partner, board_after, lambda war, f: war._play_step(f))
        assert result is board_after
        assert clicks == [(Page.PARTNER_DETAIL, (680, 165))]


def test_playcover_3_5_max_level_11_capacity_and_4col_tray():
    late = load_real_frame("calib2/137.jpg")
    assert CurrencyWars._final_boss_ready(late) is True

    err_35 = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-16_02-32-32.png"
    if err_35.is_file():
        bgr = cv2.imread(str(err_35), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        f = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert f.mobile_layout is True
        assert f.page == Page.BENCH_FULL
        assert f.stage == "3-5"
        assert f.capacity == (11, 11)
        assert f.level == 10
        assert f.gold == 32
        assert f.squad_health == 100
        assert len(f._mobile_inventory_boxes()) == 13
        orbs = f.reward_orbs()
        assert len(orbs) >= 2
        assert not any(1471 <= x <= 1575 and 231 <= y <= 335 for x, y in orbs)


def test_playcover_2_5_purple_halo_effect_selected():
    err_halo = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-16_03-12-16.png"
    if err_halo.is_file():
        bgr = cv2.imread(str(err_halo), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        f = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert f.mobile_layout is True
        assert f.page == Page.HALO
        assert f.halo_gold == 37
        assert f.halo_refresh_status() == (1, 8)
        assert [f.halo_title(0), f.halo_title(1)] == ["如履添翼", "战场学者·精英"]
        assert [f.halo_effect_selected(0), f.halo_effect_selected(1)] == [False, True]
        assert f.halo_target_present() is True


def test_playcover_3_1_rail_shop_launch_and_dismiss():
    err_rail = Path.home() / "Library/Application Support/March7thAssistant/logs/screenshots/error_2026-11-16_03-26-34.png"
    if err_rail.is_file():
        bgr = cv2.imread(str(err_rail), cv2.IMREAD_COLOR)
        assert bgr is not None and bgr.shape == (1080, 1920, 3)
        rgb = Image.fromarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        f = Frame.from_ocr(rgb, ocr.recognize_multi_lines(rgb) or [])
        assert f.mobile_layout is True
        assert f.stage == "3-1"
        assert f.page == Page.RAIL_SHOP
        assert f.rail_launch() is not None
        assert f.rail_balance == 0
        war = CurrencyWars()
        assert war._overlay_dismiss_point(f) == (360, 715)
