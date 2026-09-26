"""Background work for the Android app, without any UI code.

Analysis and downloads run on a worker thread and report through an
:class:`events.EventQueue`, the same main-thread queue the Windows app
uses; the Kivy screen drains it with ``Clock``. Everything below this
module (URL checks, playlist analysis, format plans, file names, results)
is the shared code from the repository root.
"""

import threading
import time

import events
import formats
import playlist
import urls
from logic import describe_error
from results import ItemResult, ItemStatus, JobSummary

# The two modes the Android app offers and the formats each can use. WebM
# and Opus are left out: the bundled FFmpeg has no VP9 or Opus encoder for
# the videos that would need converting.
VIDEO_AUDIO = formats.VIDEO_AUDIO
AUDIO_ONLY = formats.AUDIO_ONLY
MODE_FORMATS = {
    VIDEO_AUDIO: ("mp4", "mkv"),
    AUDIO_ONLY: ("mp3", "m4a", "flac", "wav"),
}
VIDEO_QUALITIES = list(formats.VIDEO_QUALITIES)   # Best, 2160p (4K), ..., 360p
AUDIO_QUALITIES = list(formats.AUDIO_QUALITIES)   # Best, 320 kbps, ...
# How long an analysed video's information is reused for its download.
# Media links from YouTube and most sites stay valid for hours; a stale one
# only costs a second attempt with fresh information.
REUSE_SECONDS = 20 * 60
# Progress reaches the screen at most this often; yt-dlp reports every chunk.
PROGRESS_INTERVAL = 0.25


def build_options(mode, save_path, fmt=None, quality="Best", trim_start=None, trim_end=None):
    """Options for ``DownloadManager.download_video``.

    ``quality`` is a video height limit for Video + Audio and a bitrate for
    Audio Only. Empty trim texts mean the whole video.
    """
    if mode not in MODE_FORMATS:
        raise ValueError(f"Unsupported mode '{mode}'")
    allowed = MODE_FORMATS[mode]
    qualities = VIDEO_QUALITIES if mode == VIDEO_AUDIO else AUDIO_QUALITIES
    return {
        "mode": mode,
        "format": fmt if fmt in allowed else allowed[0],
        "quality": quality if quality in qualities else "Best",
        "save_path": save_path,
        "trim_start": (trim_start or "").strip() or None,
        "trim_end": (trim_end or "").strip() or None,
    }


class Session:
    """Runs one analysis or download job at a time on a worker thread."""

    def __init__(self, manager, queue, tr=lambda key, **values: key):
        self.manager = manager
        self.events = queue
        self.tr = tr
        self._thread = None
        self._cancel = threading.Event()
        self._analysed = None  # (time, url, info) of the last single video analysed
        self._last_progress = float("-inf")

    @property
    def busy(self):
        return self._thread is not None and self._thread.is_alive()

    def _start(self, target, *args):
        if self.busy:
            return False
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=target, args=(*args, self._cancel), daemon=True)
        self._thread.start()
        return True

    def cancel(self):
        self._cancel.set()

    def wait(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    # --- Analysis -----------------------------------------------------------------

    def analyze(self, text):
        """Check the link now; fetch its info in the background.

        Raises :class:`urls.UrlError` for a link that is not worth fetching.
        """
        url = urls.normalize_url(text)
        return self._start(self._analyze, url)

    def _analyze(self, url, cancel):
        try:
            info = self.manager.fetch_info(url, log_callback=self._log)
            if info.get("error"):
                self.events.post(events.ANALYSIS_FAILED, message=info["error"])
                return
            analysis = playlist.analyze(info, url)
            if not analysis.is_playlist and analysis.items and info.get("formats"):
                self._analysed = (time.monotonic(), analysis.items[0].url, info)
            self.events.post(events.ANALYSIS_DONE, analysis=analysis, url=url)
        except Exception as e:  # never let the worker die silently
            self.events.post(events.ANALYSIS_FAILED, message=describe_error(e))

    # --- Download -----------------------------------------------------------------

    def download(self, analysis, options):
        """Download every downloadable item of ``analysis`` with ``options``."""
        items = [item.as_dict() for item in analysis.items + analysis.skipped]
        return self._start(self._download, items, options)

    def _download(self, items, options, cancel):
        summary = JobSummary()
        total = len(items)
        try:
            for position, item in enumerate(items, start=1):
                if item.get("skip_reason"):
                    result = ItemResult(item["url"], item["title"], ItemStatus.SKIPPED, error=item["skip_reason"])
                elif cancel.is_set():
                    result = ItemResult(item["url"], item["title"], ItemStatus.CANCELLED, error="Cancelled by user")
                else:
                    self.events.post(events.ITEM_STARTED, position=position, total=total, title=item["title"])
                    item_options = dict(options, playlist_index=item.get("index"),
                                        playlist_title=item.get("playlist"))
                    result = self._download_item(item, item_options, cancel)
                result.source = item
                summary.add(result)
                self.events.post(events.ITEM_DONE, result=result)
        finally:
            self.events.post(events.JOB_DONE, summary=summary)

    def _known_info(self, url):
        """The analysed information for ``url`` while it is fresh, else None."""
        if self._analysed is None:
            return None
        when, known_url, info = self._analysed
        if known_url != url or time.monotonic() - when > REUSE_SECONDS:
            return None
        return info

    def _download_item(self, item, options, cancel):
        info = self._known_info(item["url"])
        result = self._download_once(item, options, cancel, info)
        if info is not None and result.status is ItemStatus.FAILED and not cancel.is_set():
            # The saved media links may have expired; ask the site again.
            self._analysed = None
            self._log(f"Retrying with fresh information ({result.error})")
            result = self._download_once(item, options, cancel, None)
        return result

    def _download_once(self, item, options, cancel, info):
        self._last_progress = float("-inf")
        try:
            return self.manager.download_video(
                item["url"], options, self._progress, log_callback=self._log,
                title=item["title"], cancel_event=cancel, info=info)
        except Exception as e:
            return ItemResult(item["url"], item["title"], ItemStatus.FAILED, error=describe_error(e))

    # --- Hooks (worker thread) ----------------------------------------------------

    def _log(self, message):
        self.events.post(events.LOG, message=message)

    def _progress(self, d):
        stage = events.stage_from_hook(d)
        if stage is not None:
            self.events.post(events.STAGE, text=stage)
            return
        # Every hook call would redraw the screen; a few times a second is enough.
        now = time.monotonic()
        if d.get("status") == "downloading" and now - self._last_progress < PROGRESS_INTERVAL:
            return
        progress = events.progress_from_hook(d)
        if progress is not None:
            self._last_progress = now
            fraction, text = progress
            detail = events.detail_from_hook(d, left=self.tr("progress.left", time="{time}"))
            self.events.post(events.PROGRESS, fraction=fraction, text=text, detail=detail)
