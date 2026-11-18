from unittest.mock import Mock, call

import pytest
import requests

from module.config import cfg
from module.update import version_check
from module.update.version_check import (
    is_update_available,
    normalize_sha256,
    pick_asset,
)


@pytest.fixture(autouse=True)
def _clean_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setitem(cfg.config, "github_token", "")


class TestIsUpdateAvailable:
    def test_newer_version_available(self):
        assert is_update_available("1.1.0", "1.0.0") is True

    def test_same_version(self):
        assert is_update_available("1.0.0", "1.0.0") is False

    def test_older_version(self):
        assert is_update_available("0.9.0", "1.0.0") is False

    def test_with_v_prefix(self):
        assert is_update_available("v1.1.0", "v1.0.0") is True

    def test_empty_local(self):
        assert is_update_available("1.0.0", "") is True

    def test_invalid_version_returns_true(self):
        assert is_update_available("invalid", "also_invalid") is True


class TestNormalizeSha256:
    def test_valid_sha256(self):
        sha = "a" * 64
        assert normalize_sha256(sha) == sha

    def test_uppercase(self):
        sha = "A" * 64
        assert normalize_sha256(sha) == "a" * 64

    def test_with_prefix(self):
        sha = f"sha256:{'a' * 64}"
        assert normalize_sha256(sha) == "a" * 64

    def test_empty_string(self):
        assert normalize_sha256("") == ""

    def test_none(self):
        assert normalize_sha256(None) == ""

    def test_invalid_algorithm(self):
        assert normalize_sha256(f"md5:{'a' * 64}") == ""

    def test_too_short(self):
        assert normalize_sha256("abc123") == ""

    def test_too_long(self):
        assert normalize_sha256("a" * 65) == ""

    def test_with_whitespace(self):
        sha = f"  {'a' * 64}  "
        assert normalize_sha256(sha) == "a" * 64


class TestPickAsset:
    def test_pick_full(self):
        assets = [
            {"browser_download_url": "https://example.com/app.zip"},
            {"browser_download_url": "https://example.com/app-full.zip"},
        ]
        result = pick_asset(assets, full=True)
        assert result is not None
        assert "full" in result["browser_download_url"]

    def test_pick_not_full(self):
        assets = [
            {"browser_download_url": "https://example.com/app-full.zip"},
            {"browser_download_url": "https://example.com/app.zip"},
        ]
        result = pick_asset(assets, full=False)
        assert result is not None
        assert "full" not in result["browser_download_url"]

    def test_empty_assets(self):
        assert pick_asset([], full=True) is None

    def test_no_match(self):
        assets = [
            {"browser_download_url": "https://example.com/app.zip"},
        ]
        assert pick_asset(assets, full=True) is None


@pytest.fixture
def github_release():
    return {
        "tag_name": "v2026.10.23-beta1",
        "body": "- 公测更新说明",
        "html_url": "https://github.com/moesnow/March7thAssistant/releases/tag/v2026.10.23-beta1",
        "assets": [
            {"name": "update.7z", "browser_download_url": "https://example.com/update.7z"},
            {"name": "app_full.zip", "browser_download_url": "https://example.com/app_full.zip",
             "digest": "sha256:" + "a" * 64},
        ],
    }


def github_response(data):
    return Mock(status_code=200, json=Mock(return_value=data))


@pytest.fixture
def github_api(monkeypatch):
    fastest = Mock(side_effect=lambda urls, **kwargs: urls[1])
    get = Mock()
    monkeypatch.setattr(version_check, "_find_fastest_api", fastest)
    monkeypatch.setattr(version_check.requests, "get", get)
    # 单测不连接网络，包括测速请求。
    monkeypatch.setattr(version_check.requests, "head", Mock(side_effect=AssertionError("unexpected HEAD")))
    return fastest, get


class TestCheckGithub:
    @pytest.mark.parametrize("full", [True, False])
    def test_empty_fastest_falls_back_to_official(self, github_api, github_release, full):
        fastest, get = github_api
        get.side_effect = [github_response([]), github_response([github_release])]
        proxies = {"https": "http://127.0.0.1:7890"}

        result = version_check._check_github(True, "v2026.10.16", full, proxies)

        urls = version_check._GITHUB_API_PRERELEASE_URLS
        assert all(url.endswith("/releases?per_page=1") for url in urls)
        fastest.assert_called_once_with(urls, proxies=proxies)
        assert get.call_args_list == [call(urls[1], timeout=10, proxies=proxies),
                                      call(urls[0], timeout=10, proxies=proxies)]
        assert result.version == github_release["tag_name"]
        assert result.release_note == github_release["body"]
        assert result.html_url == github_release["html_url"]
        assert result.api_base == version_check.GITHUB_API_BASES[0]
        assert result.file_name == ("app_full.zip" if full else "update.7z")
        assert result.sha256 == ("a" * 64 if full else "")

    @pytest.mark.parametrize("invalid", [[], {}, None, "bad response", [None], [{}],
                                         [{"tag_name": None}], [{"tag_name": 123}],
                                         [{"tag_name": ""}], [{"tag_name": "not-a-version"}]])
    def test_invalid_data_from_all_apis_is_a_clear_failure(self, github_api, invalid):
        _, get = github_api
        get.side_effect = [github_response(invalid), github_response(invalid)]

        with pytest.raises(version_check.VersionCheckError, match="更新接口未返回有效版本信息") as error:
            version_check._check_github(True, "v2026.10.16")

        assert get.call_count == 2
        assert error.value.__cause__ is not None

    @pytest.mark.parametrize("failure", [requests.Timeout("timed out"),
                                         requests.ConnectionError("offline"),
                                         ValueError("invalid JSON"), 502])
    def test_request_failure_falls_back(self, github_api, github_release, failure):
        _, get = github_api
        response = Mock(status_code=failure) if isinstance(failure, int) else failure
        if isinstance(failure, ValueError):
            response = Mock(status_code=200, json=Mock(side_effect=failure))
        get.side_effect = [response, github_response([github_release])]

        result = version_check._check_github(True, "v2026.10.16")

        assert result.version == github_release["tag_name"]
        assert get.call_count == 2

    @pytest.mark.parametrize("prerelease", [True, False])
    @pytest.mark.parametrize("current_version", ["v2026.10.23-beta1", "v2026.10.24"])
    def test_valid_current_or_older_release_is_up_to_date(
        self, github_api, github_release, prerelease, current_version,
    ):
        _, get = github_api
        # 判断已是最新版本不依赖下载资源是否存在。
        github_release.pop("assets")
        get.return_value = github_response([github_release] if prerelease else github_release)

        assert version_check._check_github(prerelease, current_version) is None
        get.assert_called_once()

    def test_stable_release_uses_latest_endpoint(self, github_api, github_release):
        _, get = github_api
        github_release["tag_name"] = "v2026.10.23"
        get.return_value = github_response(github_release)

        result = version_check._check_github(False, "v2026.10.16")

        assert result.version == "v2026.10.23"
        assert result.api_base == version_check.GITHUB_API_BASES[1]
        get.assert_called_once_with(version_check._GITHUB_API_URLS[1], timeout=10, proxies=None)

    @pytest.mark.parametrize("invalid", [[], None, {"tag_name": ""}])
    def test_invalid_stable_response_falls_back(self, github_api, github_release, invalid):
        _, get = github_api
        github_release["tag_name"] = "v2026.10.23"
        get.side_effect = [github_response(invalid), github_response(github_release)]

        result = version_check._check_github(False, "v2026.10.16")

        assert result.version == "v2026.10.23"
        assert result.api_base == version_check.GITHUB_API_BASES[0]
        assert get.call_count == 2

    def test_official_first_also_falls_back_to_mirror(self, github_api, github_release):
        fastest, get = github_api
        fastest.side_effect = lambda urls, **kwargs: urls[0]
        get.side_effect = [github_response([]), github_response([github_release])]

        result = version_check._check_github(True, "v2026.10.16")

        assert result.api_base == version_check.GITHUB_API_BASES[1]
        assert [args.args[0] for args in get.call_args_list] == version_check._GITHUB_API_PRERELEASE_URLS

    def test_all_requests_fail_without_retrying_same_api(self, github_api):
        _, get = github_api
        get.side_effect = requests.Timeout("offline")

        with pytest.raises(version_check.VersionCheckError):
            version_check._check_github(True, "v2026.10.16")

        urls = [args.args[0] for args in get.call_args_list]
        assert len(urls) == len(set(urls)) == 2

    @pytest.mark.parametrize("configured, expected", [("", "env-token"), ("  gui-token  ", "gui-token")])
    def test_token_prefers_official_api(self, github_api, github_release, monkeypatch, configured, expected):
        fastest, get = github_api
        monkeypatch.setenv("GITHUB_TOKEN", " env-token ")
        monkeypatch.setitem(cfg.config, "github_token", configured)
        get.return_value = github_response([github_release])

        assert version_check._check_github(True, "v2026.10.16").version == github_release["tag_name"]
        fastest.assert_not_called()
        get.assert_called_once_with(
            version_check._GITHUB_API_PRERELEASE_URLS[0], timeout=10, proxies=None,
            headers={"Authorization": f"Bearer {expected}"}, allow_redirects=False,
        )

    def test_mirror_retry_does_not_receive_token(self, github_api, github_release, monkeypatch):
        _, get = github_api
        monkeypatch.setenv("GITHUB_TOKEN", "env-token")
        get.side_effect = [Mock(status_code=401), github_response(github_release)]

        assert version_check._check_github(False, "v2026.10.16").api_base == version_check.GITHUB_API_BASES[1]
        assert get.call_args == call(version_check._GITHUB_API_URLS[1], timeout=10, proxies=None)


@pytest.mark.parametrize("prerelease, full", [(False, True), (True, False)])
def test_403_uses_official_release_page_and_tag_assets(github_api, monkeypatch, prerelease, full):
    fastest, get = github_api
    releases = "https://github.com/moesnow/March7thAssistant/releases"
    tag = "v2026.12.1-beta" if prerelease else "v2026.12.1"
    if prerelease:
        api_url = version_check._GITHUB_API_PRERELEASE_URLS[1]
        expected_api_call = call(api_url, timeout=10, proxies=None)
        page_url = releases
        page = Mock(status_code=200, text=(
            f'<include-fragment src="{releases}/expanded_assets/{tag}"></include-fragment>'
            f'<include-fragment src="{releases}/expanded_assets/v2026.11.17"></include-fragment>'
        ))
    else:
        monkeypatch.setenv("GITHUB_TOKEN", "env-token")
        api_url = version_check._GITHUB_API_URLS[0]
        expected_api_call = call(api_url, timeout=10, proxies=None, allow_redirects=False,
                                 headers={"Authorization": "Bearer env-token"})
        page_url = releases + "/latest"
        page = Mock(status_code=302, headers={"Location": f"/moesnow/March7thAssistant/releases/tag/{tag}"})

    assets = Mock(status_code=200, text=f'''
        <li><a href="https://example.com/moesnow/March7thAssistant/releases/download/{tag}/fake_full.7z">镜像</a></li>
        <li><a href="{releases}/download/v2026.11.17/old_full.7z">旧版</a></li>
        <li><a href="{releases}/download/{tag}/March7thAssistant_full_android.apk">APK</a></li>
        <li><a href="/moesnow/March7thAssistant/releases/download/{tag}/March7thAssistant_full.7z">完整包</a>
            <clipboard-copy value="sha256:{'a' * 64}"></clipboard-copy></li>
        <li><a href="{releases}/download/{tag}/update.7z">更新包</a>
            <clipboard-copy value="sha256:{'b' * 64}"></clipboard-copy></li>
    ''')
    get.side_effect = [Mock(status_code=403), page, assets]
    result = version_check._check_github(prerelease, "v2026.11.17", full)

    name = "March7thAssistant_full.7z" if full else "update.7z"
    assert result.version == tag
    assert result.html_url == f"{releases}/tag/{tag}"
    assert result.url == f"{releases}/download/{tag}/{name}"
    assert result.file_name == name
    assert result.sha256 == ("a" if full else "b") * 64
    assert result.api_base is None
    assert get.call_args_list == [
        expected_api_call,
        call(page_url, timeout=10, proxies=None, allow_redirects=False),
        call(f"{releases}/expanded_assets/{tag}", timeout=10, proxies=None, allow_redirects=False),
    ]
    if not prerelease:
        fastest.assert_not_called()


def test_403_does_not_fetch_assets_when_up_to_date(github_api):
    _, get = github_api
    get.side_effect = [Mock(status_code=403), Mock(status_code=302, headers={
        "Location": "https://github.com/moesnow/March7thAssistant/releases/tag/v2026.11.17",
    })]

    assert version_check._check_github(False, "v2026.11.17") is None
    assert get.call_count == 2


def test_403_rejects_unofficial_latest_redirect(github_api):
    _, get = github_api
    get.side_effect = [Mock(status_code=403), Mock(status_code=302, headers={
        "Location": "https://example.com/moesnow/March7thAssistant/releases/tag/v2026.11.17",
    })]

    with pytest.raises(version_check.VersionCheckError, match="GitHub API 返回 HTTP 403"):
        version_check._check_github(False, "v2026.11.8")
    assert get.call_count == 2


class TestMacUpdateEditions:
    def test_edition_priority_env_over_file_over_default(self, monkeypatch, tmp_path):
        edition_file = tmp_path / "build_edition.txt"
        monkeypatch.setattr(version_check, "_BUILD_EDITION_FILE", str(edition_file))
        monkeypatch.delenv("M7A_UPDATE_EDITION", raising=False)
        assert version_check.get_update_edition() == "local"

        edition_file.write_text("share\n", encoding="utf-8")
        assert version_check.get_update_edition() == "share"

        monkeypatch.setenv("M7A_UPDATE_EDITION", "local")
        assert version_check.get_update_edition() == "local"

    def test_local_edition_strips_macos_suffix_and_checks_upstream(self, monkeypatch, github_api):
        _, get = github_api
        monkeypatch.setattr(version_check.sys, "platform", "darwin")
        monkeypatch.setenv("M7A_UPDATE_EDITION", "local")
        monkeypatch.setattr(version_check, "get_local_version", lambda: "v2026.11.15-macos.2")

        assert version_check.get_github_repo() == "moesnow/March7thAssistant"

        # Upstream is on v2026.11.15 -> stripped local is v2026.11.15 -> up to date.
        get.return_value = github_response({
            "tag_name": "v2026.11.15",
            "body": "upstream",
            "html_url": "https://github.com/moesnow/March7thAssistant/releases/tag/v2026.11.15",
            "assets": [{"name": "March7thAssistant_full.7z", "browser_download_url": "https://example.com/full.7z"}],
        })
        assert version_check.check_for_update("GitHub", prerelease=False) is None

        # Upstream hotfix v2026.11.15-1 -> detected even without a .dmg asset.
        get.return_value = github_response({
            "tag_name": "v2026.11.15-1",
            "body": "hotfix",
            "html_url": "https://github.com/moesnow/March7thAssistant/releases/tag/v2026.11.15-1",
            "assets": [{"name": "March7thAssistant.zip", "browser_download_url": "https://example.com/app.zip"}],
        })
        info = version_check.check_for_update("GitHub", prerelease=False)
        assert info is not None
        assert info.version == "v2026.11.15-1"
        assert "moesnow/March7thAssistant" in info.html_url

        # Formal check failure on local edition must NOT fall back to upstream prerelease channel.
        get.reset_mock()
        get.side_effect = [Mock(status_code=404), Mock(status_code=404)]
        with pytest.raises(version_check.VersionCheckError):
            version_check.check_for_update("GitHub", prerelease=False)
        assert get.call_count == 2

    def test_share_edition_ignores_mirrorchyan_and_checks_mac_repo_only(self, monkeypatch, github_api):
        _, get = github_api
        monkeypatch.setattr(version_check.sys, "platform", "darwin")
        monkeypatch.setenv("M7A_UPDATE_EDITION", "share")
        monkeypatch.setattr(version_check, "get_local_version", lambda: "v2026.11.15-macos.2")
        mirror = Mock(side_effect=AssertionError("share edition must never query MirrorChyan"))
        monkeypatch.setattr(version_check, "_check_mirrorchyan", mirror)

        assert version_check.get_github_repo() == "khkjdfkjhdsfakhds/March7thAssistant-macOS"

        # Remote still at v2026.11.15-macos.1 (older than local v2026.11.15-macos.2) -> None.
        get.return_value = github_response([{
            "tag_name": "v2026.11.15-macos.1",
            "body": "mac release 1",
            "html_url": "https://github.com/khkjdfkjhdsfakhds/March7thAssistant-macOS/releases/tag/v2026.11.15-macos.1",
            "assets": [{"name": "app.dmg", "browser_download_url": "https://example.com/app1.dmg"}],
        }])
        # Simulate formal latest returning 404 (pre-release only), falling back to prerelease list.
        get.side_effect = [
            Mock(status_code=404),
            Mock(status_code=404),
            github_response([{
                "tag_name": "v2026.11.15-macos.1",
                "body": "mac release 1",
                "html_url": "https://github.com/khkjdfkjhdsfakhds/March7thAssistant-macOS/releases/tag/v2026.11.15-macos.1",
                "assets": [{"name": "app.dmg", "browser_download_url": "https://example.com/app1.dmg"}],
            }]),
        ]
        assert version_check.check_for_update("MirrorChyan", cdk="secret", prerelease=False) is None
        mirror.assert_not_called()
        assert all("khkjdfkjhdsfakhds/March7thAssistant-macOS" in c.args[0] for c in get.call_args_list)

        # Remote updated to v2026.11.15-macos.3 -> returns .dmg UpdateInfo.
        get.reset_mock()
        get.side_effect = [
            Mock(status_code=404),
            Mock(status_code=404),
            github_response([{
                "tag_name": "v2026.11.15-macos.3",
                "body": "mac release 3",
                "html_url": "https://github.com/khkjdfkjhdsfakhds/March7thAssistant-macOS/releases/tag/v2026.11.15-macos.3",
                "assets": [{"name": "March7thAssistant-macOS-v2026.11.15-macos.3-arm64.dmg",
                            "browser_download_url": "https://example.com/app3.dmg"}],
            }]),
        ]
        info = version_check.check_for_update("GitHub", prerelease=False)
        assert info is not None
        assert info.version == "v2026.11.15-macos.3"
        assert info.file_name.endswith(".dmg")
