"""Background work for the Android app, without any UI code.

Analysis and downloads run on a worker thread and report through an
:class:`events.EventQueue`, the same main-thread queue the Windows app
uses; the Kivy screen drains it with ``Clock``. Everything below this
module (URL checks, playlist analysis, format plans, file names, results)
is the shared code from the repository root.
"""

import threading

import events
import formats
import playlist
import urls
from logic import describe_error
from results import ItemResult, ItemStatus, JobSummary

# The two modes the Android preview offers, with the container or audio
# format each uses.
VIDEO_AUDIO = formats.VIDEO_AUDIO
AUDIO_ONLY = formats.AUDIO_ONLY
MODE_FORMATS = {VIDEO_AUDIO: "mp4", AUDIO_ONLY: "mp3"}
VIDEO_QUALITIES = ["Best", "1080p", "720p", "480p", "360p"]


def build_options(mode, quality, save_path, audio_format=None):
    """Options for ``DownloadManager.download_video`` (no trim on Android)."""
    if mode not in MODE_FORMATS:
        raise ValueError(f"Unsupported mode '{mode}'")
    fmt = audio_format if (mode == AUDIO_ONLY and audio_format) else MODE_FORMATS[mode]
    return {
        "mode": mode,
        "format": fmt,
        "quality": quality if mode == VIDEO_AUDIO else "Best",
        "save_path": save_path,
        "trim_start": None,
        "trim_end": None,
    }


class Session:
    """Runs one analysis or download job at a time on a worker thread."""

    def __init__(self, manager, queue, tr=lambda key, **values: key):
        self.manager = manager
        self.events = queue
        self.tr = tr
        self._thread = None
        self._cancel = threading.Event()

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
            self.events.post(events.ANALYSIS_DONE, analysis=playlist.analyze(info, url), url=url)
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
                    try:
                        result = self.manager.download_video(
                            item["url"], item_options, self._progress, log_callback=self._log,
                            title=item["title"], cancel_event=cancel)
                    except Exception as e:
                        result = ItemResult(item["url"], item["title"], ItemStatus.FAILED,
                                            error=describe_error(e))
                result.source = item
                summary.add(result)
                self.events.post(events.ITEM_DONE, result=result)
        finally:
            self.events.post(events.JOB_DONE, summary=summary)

    # --- Hooks (worker thread) ----------------------------------------------------

    def _log(self, message):
        self.events.post(events.LOG, message=message)

    def _progress(self, d):
        stage = events.stage_from_hook(d)
        if stage is not None:
            self.events.post(events.STAGE, text=stage)
            return
        progress = events.progress_from_hook(d)
        if progress is not None:
            fraction, text = progress
            detail = events.detail_from_hook(d, left=self.tr("progress.left", time="{time}"))
            self.events.post(events.PROGRESS, fraction=fraction, text=text, detail=detail)
