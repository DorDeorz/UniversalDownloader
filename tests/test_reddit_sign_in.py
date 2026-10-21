"""Reddit NSFW posts: the opt-in that lends Reddit the browser's sign-in.

Reddit answers "Account authentication is required" for NSFW posts when
nobody is signed in. The desktop app can copy the reddit.com cookies of a
Firefox-based browser (Firefox, Zen, ...) and hand only those to yt-dlp;
the Android app keeps its own sign-in (a WebView).
"""

import os
import sqlite3
import sys

import pytest
import yt_dlp

import browser_cookies
import logic

REDDIT_ERROR = ("ERROR: [Reddit] 1xbqytb: Account authentication is required. Use --cookies-from-browser or "
                "--cookies for the authentication. See  https://github.com/yt-dlp/yt-dlp/wiki/FAQ#how-do-i-pass-"
                "cookies-to-yt-dlp  for how to manually pass cookies")

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


def make_profile(root, name, cookies, keep_open=False):
    """A Firefox profile folder whose cookies.sqlite (WAL mode, like Firefox) holds ``cookies``.

    With ``keep_open`` the connection stays open, so the rows are only in
    the write-ahead log, as right after the user signs in.
    """
    folder = os.path.join(root, name)
    os.makedirs(folder)
    db = sqlite3.connect(os.path.join(folder, browser_cookies.DATABASE))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA wal_autocheckpoint=0")
    db.execute("PRAGMA user_version=16")
    db.execute("CREATE TABLE moz_cookies (id INTEGER PRIMARY KEY, originAttributes TEXT NOT NULL DEFAULT '', "
               "name TEXT, value TEXT, host TEXT, path TEXT, expiry INTEGER, isSecure INTEGER)")
    db.commit()
    for host, name_, value in cookies:
        db.execute("INSERT INTO moz_cookies (name, value, host, path, expiry, isSecure) VALUES (?, ?, ?, '/', ?, 1)",
                   (name_, value, host, 4102444800000))
    db.commit()
    if keep_open:
        return folder, db
    db.close()
    return folder, None


SIGNED_IN = [(".reddit.com", "reddit_session", "abc"), ("www.reddit.com", "token_v2", "t"),
             (".youtube.com", "SAPISID", "secret"), ("accounts.google.com", "SID", "secret")]


@pytest.fixture(autouse=True)
def no_sign_in():
    yield
    logic.set_reddit_sign_in(None)


def test_only_reddit_cookies_are_copied_even_from_the_write_ahead_log(tmp_path):
    profile, db = make_profile(str(tmp_path / "zen"), "abc.Default (release)", SIGNED_IN, keep_open=True)
    source = os.path.join(profile, browser_cookies.DATABASE)
    assert os.path.getsize(source + "-wal") > 0  # the rows are still in the log
    copy = str(tmp_path / "copy")
    try:
        assert browser_cookies.copy_reddit_cookies(source, copy)
    finally:
        db.close()
    assert sorted(os.listdir(copy)) == [browser_cookies.DATABASE]  # the log is folded in
    with sqlite3.connect(os.path.join(copy, browser_cookies.DATABASE)) as check:
        hosts = {row[0] for row in check.execute("SELECT host FROM moz_cookies")}
    assert hosts == {".reddit.com", "www.reddit.com"}


def test_a_profile_without_a_reddit_session_is_signed_out(tmp_path):
    profile, _ = make_profile(str(tmp_path), "p", [("www.reddit.com", "loid", "x"), (".youtube.com", "A", "b")])
    assert not browser_cookies.copy_reddit_cookies(os.path.join(profile, "cookies.sqlite"), str(tmp_path / "c"))


def test_the_most_recently_used_profile_wins(tmp_path):
    old, _ = make_profile(str(tmp_path / "Mozilla" / "Firefox" / "Profiles"), "old", SIGNED_IN)
    new, _ = make_profile(str(tmp_path / "zen" / "Profiles"), "new", SIGNED_IN)
    os.utime(os.path.join(old, "cookies.sqlite"), (1000, 1000))
    roots = [str(tmp_path / "Mozilla" / "Firefox" / "Profiles"), str(tmp_path / "zen" / "Profiles"),
             str(tmp_path / "missing")]
    assert browser_cookies.newest_database(roots) == os.path.join(new, "cookies.sqlite")
    assert browser_cookies.newest_database([str(tmp_path / "missing")]) is None


def test_browser_names_and_windows_folders(monkeypatch):
    assert browser_cookies.browser_name(r"C:\Users\a\AppData\Roaming\zen\Profiles\x\cookies.sqlite") == "Zen"
    assert browser_cookies.browser_name("/home/a/.librewolf/x/cookies.sqlite") == "LibreWolf"
    assert browser_cookies.browser_name(r"C:\Users\a\AppData\Roaming\Mozilla\Firefox\Profiles\x\c") == "Firefox"
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", os.path.abspath("Roaming"))
    monkeypatch.setenv("LOCALAPPDATA", os.path.abspath("Local"))
    roots = browser_cookies.profile_roots()
    assert os.path.join(os.path.abspath("Roaming"), "zen", "Profiles") in roots
    assert os.path.join(os.path.abspath("Roaming"), "Mozilla", "Firefox", "Profiles") in roots


def test_yt_dlp_reads_only_reddit_cookies_from_the_copy(tmp_path):
    root = str(tmp_path / "profiles")
    make_profile(root, "p", SIGNED_IN)
    sign_in = browser_cookies.RedditSignIn(str(tmp_path / "copy"), roots=[root])
    options = sign_in.ydl_options()
    assert sign_in.status == browser_cookies.SIGNED_IN
    assert options == {"cookiesfrombrowser": ("firefox", str(tmp_path / "copy"), None, None)}
    jar = yt_dlp.cookies.extract_cookies_from_browser(*options["cookiesfrombrowser"][:2])
    assert {(c.domain, c.name) for c in jar} == {(".reddit.com", "reddit_session"), ("www.reddit.com", "token_v2")}


def test_the_copy_is_refreshed_after_a_while_and_removed_when_turned_off(tmp_path):
    root = str(tmp_path / "profiles")
    now = [0.0]
    sign_in = browser_cookies.RedditSignIn(str(tmp_path / "copy"), roots=[root], clock=lambda: now[0])
    assert sign_in.ydl_options() == {} and sign_in.status == browser_cookies.NO_BROWSER
    make_profile(root, "p", SIGNED_IN)
    now[0] = browser_cookies.REFRESH_SECONDS - 1
    assert sign_in.ydl_options() == {}  # not read again yet
    now[0] = browser_cookies.REFRESH_SECONDS
    assert sign_in.ydl_options() and sign_in.status == browser_cookies.SIGNED_IN
    sign_in.remove_copy()
    assert not os.path.exists(tmp_path / "copy")


def test_an_unreadable_database_is_reported_not_raised(tmp_path):
    folder = tmp_path / "profiles" / "p"
    folder.mkdir(parents=True)
    (folder / "cookies.sqlite").write_bytes(b"not a database")
    sign_in = browser_cookies.RedditSignIn(str(tmp_path / "copy"), roots=[str(tmp_path / "profiles")])
    assert sign_in.ydl_options() == {}
    assert sign_in.status == browser_cookies.FAILED


def test_every_yt_dlp_instance_gets_the_reddit_cookies_while_it_is_on(tmp_path):
    root = str(tmp_path / "profiles")
    make_profile(root, "p", SIGNED_IN)
    assert "cookiesfrombrowser" not in logic.base_ydl_options()
    logic.set_reddit_sign_in(browser_cookies.RedditSignIn(str(tmp_path / "copy"), roots=[root]))
    assert logic.base_ydl_options()["cookiesfrombrowser"][1] == str(tmp_path / "copy")


def test_the_sign_in_error_says_what_to_do_in_the_app(tmp_path):
    message = logic.describe_error(Exception(REDDIT_ERROR))
    assert logic.explain_site_error(message) == logic.REDDIT_SIGN_IN_OFF
    sign_in = browser_cookies.RedditSignIn(str(tmp_path / "copy"), roots=[str(tmp_path / "none")])
    sign_in.refresh()
    logic.set_reddit_sign_in(sign_in)
    assert logic.explain_site_error(message) == logic.REDDIT_SIGN_IN_MISSING
    logic.set_reddit_sign_in(browser_cookies.AppSignIn())
    assert logic.explain_site_error(message) == message  # signed in and still refused: yt-dlp's words
    assert logic.explain_site_error("[YouTube] abc: Private video") == "[YouTube] abc: Private video"


class RefusingYoutubeDL:
    def __init__(self, params):
        self.params = params

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download=False):
        raise yt_dlp.utils.DownloadError(REDDIT_ERROR)


def test_analysis_of_an_nsfw_post_explains_the_sign_in(monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", RefusingYoutubeDL)
    info = logic.DownloadManager().fetch_info("https://www.reddit.com/r/x/comments/1xbqytb/y/")
    assert info["error"] == logic.REDDIT_SIGN_IN_OFF


def test_the_messages_are_translated():
    import i18n
    i18n.set_language("tr")
    try:
        for message in (logic.REDDIT_SIGN_IN_OFF, logic.REDDIT_SIGN_IN_MISSING):
            assert i18n.tr_message(message) != message
            assert "Reddit" in i18n.tr_message(message)
    finally:
        i18n.set_language("en")


def test_the_setting_starts_off(tmp_path):
    import settings
    assert settings.load(str(tmp_path / "none.json"), str(tmp_path)).reddit_browser_sign_in is False


@pytest.fixture
def app(monkeypatch, tmp_path):
    pytest.importorskip("customtkinter")
    from ui_helpers import make_app
    root = tmp_path / "profiles"
    monkeypatch.setattr(browser_cookies, "profile_roots", lambda: [str(root)])
    window = make_app(monkeypatch)
    window.profiles = str(root)
    yield window
    window.destroy()


@needs_display
def test_the_extension_dialog_switch_turns_the_sign_in_on_and_off(app):
    import ui
    make_profile(app.profiles, "abc.Default (release)", SIGNED_IN)
    view = ui.ExtensionDialog(app)
    try:
        assert view.lbl_reddit.cget("text") == ui.tr("settings.reddit_sign_in_hint")
        view.sw_reddit.select()
        view._on_reddit_toggled()
        assert app.settings.reddit_browser_sign_in
        assert view.lbl_reddit.cget("text") == ui.tr("reddit.signed_in", browser="Firefox")
        assert "cookiesfrombrowser" in logic.base_ydl_options()
        view.sw_reddit.deselect()
        view._on_reddit_toggled()
        assert not app.settings.reddit_browser_sign_in
        assert "cookiesfrombrowser" not in logic.base_ydl_options()
    finally:
        view.destroy()


@needs_display
def test_a_refused_post_offers_the_sign_in_and_tries_again(app, monkeypatch):
    import ui
    make_profile(app.profiles, "p", SIGNED_IN)
    asked, analysed = [], []
    monkeypatch.setattr(ui.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    monkeypatch.setattr(app, "start_analysis_thread", lambda: analysed.append(True))
    app._on_analysis_failed("FAILED: ...", sign_in=True)
    assert asked and analysed
    assert app.settings.reddit_browser_sign_in

    asked.clear()
    app._on_analysis_failed("FAILED: ...", sign_in=True)  # already on: nothing to offer
    assert not asked
