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
    assert supply.choice == "补给阶段"
    assert [(lbl.text, eq, front) for lbl, eq, front in supply.supply_cards] == [
        ("缇宝", "折叠小刀", False),
        ("遐蝶", "量产型装甲", True),
        ("花火", "以太钻头", True),
        ("银狼LV.999", "幸运星", False),
        ("三月七", "轮滑鞋", False),
    ]

    garden = load_real_frame("calib/040.jpg")
    assert garden.page == Page.GARDEN
    assert [lbl.text for lbl, _ in garden.board_effect_cards] == ["画饼王", "努努斯", "奇美拉投影仪"]

    dance = load_real_frame("calib2/023.jpg")
    assert dance.page == Page.DANCE
    assert [lbl.text for lbl in dance.employee_event_candidates] == ["长夜月", "大丽花"]


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

    halo_empty = load_real_frame("calib2/062.jpg")
    assert halo_empty.page == Page.HALO
    assert [halo_empty.halo_title(i) for i in range(2)] == ["灵魂打击者", "双数跃迁"]
    assert halo_empty.halo_gold == 5
    assert [halo_empty.halo_effect_selected(i) for i in range(2)] == [False, False]
    assert halo_empty.halo_target_present() is False

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


def test_playcover_preselected_investment_recovery(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    import tasks.weekly.currency_wars as cw_task

    base = load_real_frame("calib2/076.jpg")
    pixels = base.pixels.copy()
    pixels[405:755, 202:212] = 210
    pixels[405:755, 592:602] = 210
    pixels[970:1005, 920:1045] = 220
    frame = Frame(Image.fromarray(pixels), base.labels)
    assert frame.page == Page.CHOICE
    assert frame.mobile_layout is True
    assert frame.selected_investment_column() == 0
    assert frame.choice_confirm() is not None

    after = load_real_frame("calib2/009.jpg")
    now = [0.0]
    cfg = SimpleNamespace(
        currencywars_type="normal",
        currencywars_rank_difficulty="current",
        currencywars_fast_mode=False,
        currencywars_bonus_enable=False,
        currencywars_strategy="s2_anaxa",
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
    assert war._choose(frame) is after
    assert clicks == [(Page.CHOICE, (984, 987))]
