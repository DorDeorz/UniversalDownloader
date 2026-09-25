"""TikTok needs browser impersonation (curl_cffi) in yt-dlp."""

import build_app
import logic
import yt_dlp


def test_pinned_dependencies_provide_impersonation():
    # Without curl_cffi, TikTok answers yt-dlp with a challenge page and
    # every TikTok download fails.
    assert logic.impersonation_available()


def test_tiktok_extractor_can_use_an_impersonation_target():
    with yt_dlp.YoutubeDL({'logger': logic.YtDlpLogger()}) as ydl:
        ie = ydl.get_info_extractor('TikTok')
        assert ie.suitable('https://www.tiktok.com/@user/video/7123456789012345678')
        # The same check the extractor makes when it asks for impersonation.
        assert ydl._impersonate_target_available(yt_dlp.networking.impersonate.ImpersonateTarget())


def test_tiktok_short_links_are_recognised():
    with yt_dlp.YoutubeDL({'logger': logic.YtDlpLogger()}) as ydl:
        for url in ('https://vm.tiktok.com/ZMabcdEFg/', 'https://vt.tiktok.com/ZSabcdEFg/'):
            assert ydl.get_info_extractor('TikTokVM').suitable(url)


def test_requirements_pin_curl_cffi():
    with open('requirements.txt', encoding='utf-8') as f:
        assert 'curl-cffi==' in f.read()


def test_preflight_rejects_a_build_without_impersonation():
    assert build_app.check_impersonation(True) is None
    problem = build_app.check_impersonation(False)
    assert 'curl_cffi' in problem


def test_missing_impersonation_is_logged(monkeypatch, caplog):
    monkeypatch.setattr(logic, 'impersonation_available', lambda: False)
    monkeypatch.setattr(logic.media_tools, 'find_tools', lambda: object())
    monkeypatch.setattr(logic.media_tools, 'activate', lambda tools: None)
    with caplog.at_level('WARNING', logger='logic'):
        logic.DownloadManager().ensure_tools()
    assert 'curl_cffi is missing' in caplog.text
