"""Playlist validation (ISSUES.md #16-#18, #21, #22, #24, #36)."""

import os
import sys
import time

import pytest

import playlist


def entry(i, **kw):
    base = {"id": f"id{i}", "title": f"Video {i}", "url": f"https://www.youtube.com/watch?v=id{i}",
            "ie_key": "Youtube"}
    base.update(kw)
    return base


def test_single_video_becomes_one_item():
    result = playlist.analyze({"title": "Clip", "webpage_url": "https://x/v", "duration": 12}, "https://x/v?s=1")
    assert not result.is_playlist
    assert [(i.url, i.title, i.duration) for i in result.items] == [("https://x/v", "Clip", 12)]


def test_live_single_video_is_skipped():
    result = playlist.analyze({"title": "Live", "is_live": True}, "https://x/live")
    assert result.items == []
    assert result.skipped[0].skip_reason == "live stream"


@pytest.mark.parametrize("entries", [None, [], iter(())])
def test_empty_or_missing_entries_do_not_crash(entries):
    result = playlist.analyze({"_type": "playlist", "title": "Empty", "entries": entries}, "u")
    assert result.is_playlist
    assert result.items == [] and result.skipped == []


def test_unavailable_entries_are_skipped_with_reason():
    info = {"_type": "playlist", "title": "Mix", "entries": [
        entry(1),
        None,
        entry(3, title="[Private video]"),
        entry(4, title="[Deleted video]"),
        entry(5, availability="needs_auth"),
        entry(6, live_status="is_upcoming"),
        entry(7, url=None, ie_key="Generic", webpage_url=None),
        entry(8, _type="url", ie_key="YoutubeTab", url="https://www.youtube.com/playlist?list=x"),
        entry(9, availability="public"),
    ]}
    result = playlist.analyze(info, "u")

    assert [i.index for i in result.items] == [1, 9]
    assert [(i.index, i.skip_reason) for i in result.skipped] == [
        (2, "unavailable"),
        (3, "private video"),
        (4, "deleted video"),
        (5, "sign-in required"),
        (6, "not yet available (upcoming)"),
        (7, "no downloadable URL"),
        (8, "nested playlist (open it separately)"),
    ]
    assert result.total == 9


def test_entries_keep_playlist_position_and_title():
    info = {"title": "My List", "entries": [entry(1, playlist_index=4), entry(2)]}
    items = playlist.analyze(info, "u").items
    assert [(i.index, i.playlist) for i in items] == [(4, "My List"), (2, "My List")]


def test_youtube_id_only_entry_gets_watch_url():
    assert playlist.entry_url({"id": "abc", "ie_key": "Youtube"}) == "https://www.youtube.com/watch?v=abc"


def test_non_youtube_id_is_not_turned_into_youtube_url():
    assert playlist.entry_url({"id": "abc", "ie_key": "Vimeo"}) is None


def test_relative_url_is_not_used():
    assert playlist.entry_url({"url": "abc123"}) is None


def test_as_dict_drops_empty_fields():
    assert playlist.QueueItem(url="u", title="t").as_dict() == {"url": "u", "title": "t"}


# --- selector dialog -----------------------------------------------------

ctk = pytest.importorskip("customtkinter")
pytest.importorskip("tkinter.messagebox")

import ui  # noqa: E402
from ui_helpers import make_app  # noqa: E402

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)


@pytest.fixture
def app(monkeypatch):
    window = make_app(monkeypatch)
    yield window
    window.destroy()


def make_analysis(n, skipped=0):
    info = {"title": "List", "entries": [entry(i) for i in range(1, n + 1)]
            + [entry(100 + i, title="[Private video]") for i in range(skipped)]}
    return playlist.analyze(info, "u")


def pump(app, seconds=0.3):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.update()
        time.sleep(0.01)


@needs_display
def test_selector_confirm_returns_selected_items(app):
    got = []
    dialog = ui.PlaylistSelector(app, make_analysis(3, skipped=1), got.append)
    pump(app)
    dialog.vars[1].set(0)
    dialog._update_count()
    assert dialog.lbl_count.cget("text") == "2 selected"

    dialog.confirm_selection()

    assert [[i.index for i in items] for items in got] == [[1, 3]]


@needs_display
def test_selector_cannot_confirm_empty_selection(app):
    got = []
    dialog = ui.PlaylistSelector(app, make_analysis(2), got.append)
    pump(app)
    dialog.select_none()

    assert dialog.btn_confirm.cget("state") == "disabled"
    dialog.confirm_selection()
    assert got == []
    dialog.cancel()


@needs_display
def test_closing_selector_is_a_cancel(app):
    got = []
    dialog = ui.PlaylistSelector(app, make_analysis(2), got.append)
    pump(app)

    dialog.cancel()
    dialog.cancel()

    assert got == [None]


@needs_display
def test_large_playlist_rows_are_built_in_batches(app):
    dialog = ui.PlaylistSelector(app, make_analysis(180), lambda items: None)
    assert len(dialog.vars) == ui.PlaylistSelector.BATCH
    pump(app, 1.0)
    assert len(dialog.vars) == 180
    dialog.cancel()


@needs_display
def test_app_queues_selection_only_if_url_unchanged(app):
    app.url_entry.insert(0, "https://www.youtube.com/playlist?list=x")
    app._on_analysis_done(make_analysis(2), "https://www.youtube.com/playlist?list=x")
    pump(app)
    app.playlist_dialog.confirm_selection()
    assert [i["index"] for i in app.download_queue] == [1, 2]
    assert app.download_queue[0]["playlist"] == "List"


@needs_display
def test_app_warns_when_playlist_has_nothing_downloadable(app, monkeypatch):
    warned = []
    monkeypatch.setattr(ui.messagebox, "showwarning", lambda *a, **k: warned.append(a))
    app._on_analysis_done(make_analysis(0, skipped=2), "u")
    assert warned and app.playlist_dialog is None
    assert app.download_queue == []


@needs_display
def test_skipped_entries_are_reported_in_the_job_summary(app, monkeypatch):
    from results import ItemResult, ItemStatus

    class Manager:
        def download_video(self, url, options, progress_hook=None, log_callback=None, title=None,
                           cancel_event=None, **kw):
            return ItemResult(url, title, ItemStatus.COMPLETED, path="/x")

    monkeypatch.setattr(ui.messagebox, "showinfo", lambda *a, **k: None)
    app.manager = Manager()
    app.url_entry.insert(0, "u")
    app._on_analysis_done(make_analysis(1, skipped=2), "u")
    pump(app)
    app.playlist_dialog.confirm_selection()
    app.start_download_queue()
    deadline = time.monotonic() + 5
    while app.is_busy() and time.monotonic() < deadline:
        pump(app, 0.05)

    assert app.last_summary.headline() == "1 completed, 2 skipped"
