"""Orbida 1.2.4: the remaining suggestions of the code reviews (shared code, no window)."""

import http.server
import logging
import os
import threading

import pytest

import app_setup
import logic
import media_tools


class _Answer(http.server.BaseHTTPRequestHandler):
    """A site, and a plain HTTP proxy: a request names the full address (or only the path)."""

    seen = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        _Answer.seen.append(self.path)
        self.send_response(204)
        self.end_headers()


@pytest.fixture
def local_site():
    _Answer.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Answer)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    old = {k: os.environ.get(k) for k in ("NO_PROXY", "no_proxy")}
    os.environ["NO_PROXY"] = os.environ["no_proxy"] = "127.0.0.1,localhost"
    yield f"127.0.0.1:{server.server_port}"
    server.shutdown()
    for k, v in old.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


# --- Settings › Test connection (review #31) -----------------------------------------

def test_connection_test_reports_the_time_taken(local_site):
    seconds, error = logic.check_connection("", f"http://{local_site}/generate_204")
    assert error is None and 0 <= seconds < 5
    assert _Answer.seen == ["/generate_204"]


def test_connection_test_goes_through_the_proxy(local_site):
    seconds, error = logic.check_connection(f"http://{local_site}", "http://example.invalid/generate_204")
    assert error is None
    assert _Answer.seen == ["http://example.invalid/generate_204"]  # the proxy was asked for the address


def test_connection_test_names_the_problem():
    seconds, error = logic.check_connection("http://127.0.0.1:9", "http://example.invalid/x", timeout=3)
    assert seconds is None and error


# --- Detailed log (review #13) -------------------------------------------------------

def test_detailed_log_turns_on_debug_output():
    try:
        logic.set_verbose(True)
        app_setup.set_verbose_logging(True)
        assert logic.base_ydl_options()["verbose"] is True
        assert logging.getLogger().level == logging.DEBUG
    finally:
        logic.set_verbose(False)
        app_setup.set_verbose_logging(False)
    assert "verbose" not in logic.base_ydl_options()
    assert logging.getLogger().level == logging.INFO


# --- Copy diagnostics (review #29) ---------------------------------------------------

def test_diagnostics_name_versions_settings_and_the_end_of_the_log(tmp_path):
    import settings as settings_store
    log = tmp_path / "app.log"
    log.write_text("\n".join(f"line {i}" for i in range(500)), encoding="utf-8")
    current = settings_store.Settings(proxy="http://user:secret@proxy:8080", download_folder="C:\\Users\\Me\\Videos")
    tools = media_tools.ToolStatus(True, directory="/bin", version="7.1", source="bundled")
    text = app_setup.diagnostics(current, tools, "2026.10.21", str(log), lines=100)
    assert text.startswith("Orbida ") and "yt-dlp 2026.10.21" in text and "FFmpeg 7.1" in text
    assert "secret" not in text and '"proxy": "(set)"' in text
    assert "Users" not in text  # the folder names the user
    assert "line 499" in text and "line 399" not in text and "line 400" in text


def test_log_tail_of_a_missing_file_is_empty(tmp_path):
    assert app_setup.log_tail(str(tmp_path / "none.log")) == ""
