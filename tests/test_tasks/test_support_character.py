"""支援头像仅在原匹配未选到目标时使用角标遮罩重试。"""

from unittest.mock import Mock

from tasks.power import character


def test_support_avatar_retries_with_corner_mask(monkeypatch):
    match = ((48, 477), (156, 578))
    find_element = Mock(side_effect=[[], [match]])
    click = Mock()
    monkeypatch.setattr(character.auto, "find_element", find_element)
    monkeypatch.setattr(character.auto, "click_element_with_pos", click)
    monkeypatch.setattr(character.time, "sleep", lambda _: None)

    assert character.Character.find_character_and_click("Cyrene", "", 0, 0, 1920, 1080)
    assert find_element.call_count == 2
    assert find_element.call_args_list[0].kwargs["mask_top_right_ratio"] is None
    assert find_element.call_args_list[1].kwargs["mask_top_right_ratio"] == 0.26
    click.assert_called_once_with(match, (0, 0))


def test_support_avatar_uses_original_match_without_retry(monkeypatch):
    match = ((48, 477), (156, 578))
    find_element = Mock(return_value=[match])
    monkeypatch.setattr(character.auto, "find_element", find_element)
    monkeypatch.setattr(character.auto, "click_element_with_pos", Mock())
    monkeypatch.setattr(character.time, "sleep", lambda _: None)

    assert character.Character.find_character_and_click("Cyrene", "", 0, 0, 1920, 1080)
    find_element.assert_called_once()


def test_support_avatar_retries_after_friend_name_does_not_match(monkeypatch):
    first_match = ((48, 333), (156, 434))
    badge_match = ((48, 477), (156, 578))
    find_element = Mock(side_effect=[[first_match], [badge_match]])
    click_text = Mock(side_effect=[False, True])
    monkeypatch.setattr(character.auto, "find_element", find_element)
    monkeypatch.setattr(character.auto, "click_element", click_text)
    monkeypatch.setattr(character.time, "sleep", lambda _: None)

    assert character.Character.find_character_and_click("Cyrene", "指定好友", 0, 0, 1920, 1080)
    assert find_element.call_count == 2
    assert click_text.call_count == 2
    assert find_element.call_args_list[1].kwargs["mask_top_right_ratio"] == 0.26


def test_support_avatar_still_skips_when_both_matches_fail(monkeypatch):
    find_element = Mock(return_value=[])
    click = Mock()
    monkeypatch.setattr(character.auto, "find_element", find_element)
    monkeypatch.setattr(character.auto, "click_element_with_pos", click)

    assert not character.Character.find_character_and_click("Cyrene", "", 0, 0, 1920, 1080)
    assert find_element.call_count == 2
    click.assert_not_called()


def test_click_support_button_retries_after_confirming_challenge_and_support(monkeypatch):
    import pytest
    from module import mobile

    @pytest.mark.parametrize  # no-op marker avoided below; direct loop over cases
    def _case():
        pass

    cases = [
        ("standard", character.SUPPORT_BUTTON_CROPS["standard"], character.SUPPORT_RETRY_CROPS["standard"], (1720, 985), (980, 970), False),
        ("ornament", character.SUPPORT_BUTTON_CROPS["ornament"], character.SUPPORT_RETRY_CROPS["ornament"], (1720, 985), (630, 880), False),
        ("standard", character.SUPPORT_BUTTON_CROPS["standard"], character.SUPPORT_RETRY_CROPS["standard"], (1720, 985), (780, 970), True),
    ]
    for kind, support_crop, retry_crop, start_pt, supp_pt, is_mobile in cases:
        monkeypatch.setattr(mobile, "is_mobile", lambda flag=is_mobile: flag)
        mapped_retry = mobile.map_crop(retry_crop)
        frame_left, frame_top = round(mapped_retry[0] * 1920), round(mapped_retry[1] * 1080)
        frame_w, frame_h = round(mapped_retry[2] * 1920), round(mapped_retry[3] * 1080)
        start_box = (start_pt, (start_pt[0] + 80, start_pt[1] + 20))
        supp_box = (supp_pt, (supp_pt[0] + 40, supp_pt[1] + 20))

        title_calls = []

        def find(target, _kind, *_args, **kwargs):
            if target == "支援" and kwargs.get("need_ocr") is False:
                assert kwargs.get("take_screenshot") is False
                return supp_box
            if target == "支援":
                assert kwargs["crop"] == support_crop
                return supp_box
            if target == "开始挑战":
                assert kwargs["crop"] == retry_crop
                auto.screenshot_pos = (frame_left, frame_top, frame_w, frame_h)
                auto.screenshot_scale_factor = 1.0
                return start_box
            if target == character.SUPPORT_LIST_TITLES:
                title_calls.append(1)
                return ((160, 25), (260, 75)) if len(title_calls) == 2 else None
            return None

        click_pos = Mock()
        auto = Mock(find_element=Mock(side_effect=find), click_element_with_pos=click_pos)
        monkeypatch.setattr(character, "auto", auto)
        monkeypatch.setattr(character.time, "sleep", Mock())

        assert character.Character.click_support_button(kind) is True
        assert click_pos.call_count == 2


def test_click_support_button_skips_retry_when_button_or_challenge_outside(monkeypatch):
    from module import mobile

    monkeypatch.setattr(mobile, "is_mobile", lambda: False)
    supp_box = ((980, 970), (1020, 990))
    wrong_start_box = ((1220, 985), (1300, 1005))  # outside CHALLENGE

    def find(target, _kind, *_args, **kwargs):
        if target == "支援":
            return supp_box
        if target == "开始挑战":
            retry_crop = character.SUPPORT_RETRY_CROPS["standard"]
            auto.screenshot_pos = (
                round(retry_crop[0] * 1920), round(retry_crop[1] * 1080),
                round(retry_crop[2] * 1920), round(retry_crop[3] * 1080),
            )
            auto.screenshot_scale_factor = 1.0
            return wrong_start_box
        return None

    click_pos = Mock()
    auto = Mock(find_element=Mock(side_effect=find), click_element_with_pos=click_pos)
    monkeypatch.setattr(character, "auto", auto)
    monkeypatch.setattr(character.time, "sleep", Mock())

    assert character.Character.click_support_button("standard") is False
    click_pos.assert_called_once_with(supp_box)
