import sys
import json
import pytest
from unittest.mock import patch, MagicMock


def test_star_rail_setting_importable_and_safe_without_winreg(monkeypatch):
    import importlib
    import utils.registry.star_rail_setting as srs

    monkeypatch.setattr(srs, "winreg", None)
    assert srs.get_server_by_registry() is None
    assert srs.get_registry_key_path() is None
    assert srs.read_game_hotkeys("StarRail.exe") == {}

    # Also verify module import succeeds when winreg is absent (as on darwin).
    monkeypatch.delitem(sys.modules, "winreg", raising=False)
    reloaded = importlib.reload(srs)
    assert reloaded.read_game_hotkeys("StarRail.exe") == {}


def test_read_game_hotkeys_uses_selected_client_and_decodes_supported_bindings(monkeypatch, tmp_path):
    import utils.registry.star_rail_setting as srs

    data = tmp_path / "StarRail_Data"
    data.mkdir()
    (data / "app.info").write_text("miHoYo\n崩坏：星穹铁道\n", encoding="utf-8")

    mock_winreg = MagicMock()
    mock_winreg.HKEY_CURRENT_USER = 1
    mock_winreg.REG_DWORD = 4
    values = {
        "HotkeysSettings_Menu_MazeInteract_Keyboard_h2537131863": 76,
        "HotkeysSettings_Menu_BattleAvatarDetail_Keyboard_h1744695036": 25,
        "HotkeysSettings_Menu_MazeSkill_Keyboard_h1042695892": 76,
        "HotkeysSettings_Maze_Map_Keyboard_h1833719210": 46,
        "HotkeysSettings_Maze_Gacha_Keyboard_h3861591226": 25,
        "HotkeysSettings_Menu_PhoneMessage_Keyboard_h3569468801": 31,
        "HotkeysSettings_Menu_BattleAuto_Keyboard_h3719200595": 70,
    }
    mock_winreg.QueryValueEx.side_effect = lambda _key, name: (values[name], mock_winreg.REG_DWORD)
    monkeypatch.setattr(srs, "winreg", mock_winreg)

    assert srs.read_game_hotkeys(str(tmp_path / "StarRail.exe")) == {
        "hotkey_interact": "space",
        "hotkey_character_details": "f12",
        "hotkey_technique": "space",
        "hotkey_map": "k",
        "hotkey_warp": "f12",
        "hotkey_message": "5",
        "hotkey_auto_battle": ";",
    }


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
def test_detected_game_key_names_work_in_both_local_inputs():
    from pyautogui import isValidKey
    from module.automation.background_input import _vk
    from utils.registry.star_rail_setting import _KEY_NAMES_BY_CODE

    for key in _KEY_NAMES_BY_CODE.values():
        assert isValidKey(key), key
        assert _vk(key) > 0, key


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingReadRegistryValue:
    def test_none_sub_key_raises(self):
        from utils.registry.star_rail_setting import read_registry_value
        with pytest.raises(Exception, match="Registry key path not found"):
            read_registry_value(0, None, "value")

    def test_returns_value(self):
        from utils.registry.star_rail_setting import read_registry_value
        mock_key = MagicMock()
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.OpenKey.return_value = mock_key
            mock_winreg.QueryValueEx.return_value = ("test_value", 1)
            result = read_registry_value(0, "some\\path", "test_name")
            assert result == "test_value"

    def test_file_not_found_returns_none(self):
        from utils.registry.star_rail_setting import read_registry_value
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            result = read_registry_value(0, "some\\path", "test_name")
            assert result is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingWriteRegistryValue:
    def test_none_sub_key_raises(self):
        from utils.registry.star_rail_setting import write_registry_value
        with pytest.raises(Exception, match="Registry key path not found"):
            write_registry_value(0, None, "name", "data", 0)

    def test_writes_successfully(self):
        from utils.registry.star_rail_setting import write_registry_value
        mock_key = MagicMock()
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.CreateKey.return_value = mock_key
            mock_winreg.REG_BINARY = 3
            write_registry_value(0, "some\\path", "name", b"data", 3)
            mock_winreg.SetValueEx.assert_called_once_with(mock_key, "name", 0, 3, b"data")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingGetServer:
    def test_cn_server(self):
        from utils.registry.star_rail_setting import get_server_by_registry
        mock_key = MagicMock()
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.return_value = mock_key
            result = get_server_by_registry()
            assert result == "cn"

    def test_global_server(self):
        from utils.registry.star_rail_setting import get_server_by_registry
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            call_count = [0]
            def open_key_side_effect(key, path):
                call_count[0] += 1
                if call_count[0] == 1:
                    raise FileNotFoundError
                return MagicMock()
            mock_winreg.OpenKey.side_effect = open_key_side_effect
            result = get_server_by_registry()
            assert result == "global"

    def test_no_server(self):
        from utils.registry.star_rail_setting import get_server_by_registry
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            result = get_server_by_registry()
            assert result is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingGetRegistryKeyPath:
    def test_cn_path(self):
        from utils.registry.star_rail_setting import get_registry_key_path
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.return_value = MagicMock()
            result = get_registry_key_path()
            assert "miHoYo" in result

    def test_no_path(self):
        from utils.registry.star_rail_setting import get_registry_key_path
        with patch("utils.registry.star_rail_setting.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            result = get_registry_key_path()
            assert result is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingResolution:
    def test_get_resolution_valid(self):
        from utils.registry.star_rail_setting import get_game_resolution
        data = json.dumps({"width": 1920, "height": 1080, "isFullScreen": True}) + "\x00"
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=data.encode('utf-8')):
            result = get_game_resolution()
            assert result == (1920, 1080, True)

    def test_get_resolution_none(self):
        from utils.registry.star_rail_setting import get_game_resolution
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=None):
            result = get_game_resolution()
            assert result is None

    def test_get_resolution_invalid_format(self):
        from utils.registry.star_rail_setting import get_game_resolution
        data = json.dumps({"bad": "data"}) + "\x00"
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=data.encode('utf-8')):
            with pytest.raises(ValueError, match="missing required fields"):
                get_game_resolution()

    def test_get_resolution_invalid_types(self):
        from utils.registry.star_rail_setting import get_game_resolution
        data = json.dumps({"width": "1920", "height": "1080", "isFullScreen": "yes"}) + "\x00"
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=data.encode('utf-8')):
            with pytest.raises(ValueError, match="invalid"):
                get_game_resolution()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingFps:
    def test_set_fps_preserves_other_settings(self):
        from utils.registry.star_rail_setting import set_game_fps
        data = b'{"FPS": 60, "Quality": 3}\x00'
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=data), \
                patch("utils.registry.star_rail_setting.write_registry_value") as write:
            set_game_fps(120)
        assert json.loads(write.call_args.args[3].decode().strip('\x00')) == {"FPS": 120, "Quality": 3}

    def test_get_fps_valid(self):
        from utils.registry.star_rail_setting import get_game_fps
        data = json.dumps({"FPS": 120}) + "\x00"
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=data.encode('utf-8')):
            result = get_game_fps()
            assert result == 120

    def test_get_fps_default_60(self):
        from utils.registry.star_rail_setting import get_game_fps
        data = json.dumps({"other": "data"}) + "\x00"
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=data.encode('utf-8')):
            result = get_game_fps()
            assert result == 60

    def test_get_fps_none(self):
        from utils.registry.star_rail_setting import get_game_fps
        with patch("utils.registry.star_rail_setting.read_registry_value", return_value=None):
            result = get_game_fps()
            assert result is None


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestStarRailSettingSetters:
    def test_set_auto_battle(self):
        from utils.registry.star_rail_setting import set_auto_battle_open_setting
        with patch("utils.registry.star_rail_setting.write_registry_value") as mock_write:
            with patch("utils.registry.star_rail_setting.registry_key_path", "some\\path"):
                set_auto_battle_open_setting(True)
                mock_write.assert_called_once()

    def test_set_resolution(self):
        from utils.registry.star_rail_setting import set_game_resolution
        with patch("utils.registry.star_rail_setting.write_registry_value") as mock_write:
            with patch("utils.registry.star_rail_setting.registry_key_path", "some\\path"):
                set_game_resolution(1920, 1080, True)
                mock_write.assert_called_once()
                written_data = mock_write.call_args[0][3]
                decoded = json.loads(written_data.decode('utf-8').strip('\x00'))
                assert decoded['width'] == 1920
                assert decoded['height'] == 1080
                assert decoded['isFullScreen'] is True


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestGameAutoHdr:
    def test_relative_path_raises(self):
        from utils.registry.game_auto_hdr import get_game_auto_hdr
        with pytest.raises(ValueError, match="not an absolute path"):
            get_game_auto_hdr("relative/path")

    def test_set_relative_path_raises(self):
        from utils.registry.game_auto_hdr import set_game_auto_hdr
        with pytest.raises(ValueError, match="not an absolute path"):
            set_game_auto_hdr("relative/path")

    def test_get_unset(self):
        from utils.registry.game_auto_hdr import get_game_auto_hdr
        with patch("utils.registry.game_auto_hdr.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            result = get_game_auto_hdr("C:\\game\\StarRail.exe")
            assert result == "unset"

    def test_get_enable(self):
        from utils.registry.game_auto_hdr import get_game_auto_hdr
        mock_key = MagicMock()
        with patch("utils.registry.game_auto_hdr.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
            mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
            mock_winreg.QueryValueEx.return_value = ("AutoHDREnable=2097;", 1)
            result = get_game_auto_hdr("C:\\game\\StarRail.exe")
            assert result == "enable"

    def test_get_disable(self):
        from utils.registry.game_auto_hdr import get_game_auto_hdr
        mock_key = MagicMock()
        with patch("utils.registry.game_auto_hdr.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.return_value.__enter__ = MagicMock(return_value=mock_key)
            mock_winreg.OpenKey.return_value.__exit__ = MagicMock(return_value=False)
            mock_winreg.QueryValueEx.return_value = ("AutoHDREnable=2096;", 1)
            result = get_game_auto_hdr("C:\\game\\StarRail.exe")
            assert result == "disable"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only")
class TestGameAccount:
    def test_get_reg_path_cn(self):
        from utils.registry.gameaccount import get_reg_path
        mock_key = MagicMock()
        with patch("utils.registry.gameaccount.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.return_value = mock_key
            result = get_reg_path()
            assert "miHoYo" in result

    def test_get_reg_path_none(self):
        from utils.registry.gameaccount import get_reg_path
        with patch("utils.registry.gameaccount.winreg") as mock_winreg:
            mock_winreg.HKEY_CURRENT_USER = 0
            mock_winreg.OpenKey.side_effect = FileNotFoundError
            result = get_reg_path()
            assert result is None
