"""A song opened inside a YouTube Mix: the song alone, the Mix on request."""

import os
import sys

import pytest

import urls

needs_display = pytest.mark.skipif(
    not (sys.platform.startswith("win") or sys.platform == "darwin" or os.environ.get("DISPLAY")),
    reason="needs a display for Tk",
)

SONG_IN_MIX = "https://www.youtube.com/watch?v=abc&list=RDabc&start_radio=1"


def test_the_mix_link_is_kept_for_later():
    assert urls.youtube_mix(SONG_IN_MIX) == SONG_IN_MIX
    assert urls.youtube_mix("youtube.com/watch?v=abc&list=RDabc") == "https://youtube.com/watch?v=abc&list=RDabc"
    for other in ("https://www.youtube.com/watch?v=abc", "https://www.youtube.com/watch?v=abc&list=PLx",
                  "https://www.youtube.com/playlist?list=RDabc", "https://example.com/watch?v=a&list=RDa", ""):
        assert urls.youtube_mix(other) is None


@pytest.fixture
def app(monkeypatch, tmp_path):
    pytest.importorskip("customtkinter")
    from ui_helpers import make_app
    from test_ui_queue import QueueManager

    class MixManager(QueueManager):
        def __init__(self, tools):
            super().__init__(tools)
            self.analyzed = []

        def fetch_info(self, url, log_callback=None, cancel_event=None):
            self.analyzed.append(url)
            if "list=RD" in url:
                return {"_type": "playlist", "title": "Mix", "entries": [
                    {"title": "One", "url": "https://www.youtube.com/watch?v=abc"},
                    {"title": "Two", "url": "https://www.youtube.com/watch?v=def"}]}
            return super().fetch_info(url)

    window = make_app(monkeypatch)
    window.manager = MixManager(window.tools)
    window.manager.release.set()
    window.settings.show_summary = False
    window.download_folder = str(tmp_path)
    yield window
    window.destroy()


@needs_display
def test_the_song_is_analyzed_alone_and_the_mix_is_offered(app):
    from ui_helpers import pump
    pump(app, timeout=0.5)  # past the paste at start
    app._hide_copied()
    app.url_entry.delete(0, "end")
    app.url_entry.insert(0, SONG_IN_MIX)
    app.start_analysis_thread()
    assert pump(app, lambda: app.download_queue and not app.is_busy())
    assert app.manager.analyzed == ["https://www.youtube.com/watch?v=abc"]
    assert len(app.download_queue) == 1
    assert app.copied_row.winfo_ismapped() or app.copied_row.grid_info()
    assert app.btn_copied.cget("text") == app_tr("mix.download")

    app.btn_copied.invoke()  # Download the Mix
    # The Mix is a playlist: the picker opens with its songs.
    assert pump(app, lambda: getattr(app, "playlist_dialog", None) is not None and not app.is_busy())
    assert app.manager.analyzed[-1] == SONG_IN_MIX
    assert not app.copied_row.grid_info()


@needs_display
def test_a_plain_link_offers_nothing(app):
    from ui_helpers import pump
    pump(app, timeout=0.5)
    app._hide_copied()
    app.url_entry.delete(0, "end")
    app.url_entry.insert(0, "https://www.youtube.com/watch?v=abc")
    app.start_analysis_thread()
    assert pump(app, lambda: app.download_queue and not app.is_busy())
    assert not app.copied_row.grid_info()


def app_tr(key):
    from i18n import tr
    return tr(key)
