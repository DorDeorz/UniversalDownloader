import copy
import logging
import os
import re
import shutil
import time
import yt_dlp
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor
from yt_dlp.postprocessor.sponsorblock import SponsorBlockPP

import browser_cookies
import filenames
import formats
import media_tools
import playlist
import resume
import spotify
from results import ItemResult, ItemStatus, probe_output, verify_output

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())


class YtDlpLogger:
    """Routes yt-dlp messages to a callback instead of hiding them.

    yt-dlp calls debug/info/warning/error on this object. Warnings and
    errors go to ``log_callback`` (e.g. the UI log) and to the module
    logger; debug/info chatter only goes to the module logger.
    """

    def __init__(self, log_callback=None, cancel_event=None):
        self.log_callback = log_callback
        self.cancel_event = cancel_event
        self.errors = []

    def _check_cancel(self):
        # yt-dlp reports every page it reads; a cancelled analysis stops at the next one.
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise yt_dlp.utils.DownloadCancelled('Cancelled by user')

    def _emit(self, level, prefix, msg):
        msg = strip_ansi(msg).replace('\r', '')
        _log.log(level, msg)
        if self.log_callback is not None:
            self.log_callback(f"{prefix}{msg}")

    def debug(self, msg):
        # yt-dlp routes its normal screen output through debug() as well.
        _log.debug(msg)
        self._check_cancel()

    def info(self, msg):
        _log.info(msg)
        self._check_cancel()

    def warning(self, msg):
        self._emit(logging.WARNING, "Warning: ", msg)

    def error(self, msg):
        self.errors.append(describe_error(msg))
        self._emit(logging.ERROR, "", msg)


# Options a platform adds to every YoutubeDL instance (see
# set_platform_options). The Windows app adds none; the Android app points
# yt-dlp at its bundled QuickJS because Deno is not available there.
_platform_options = {}


def set_platform_options(options):
    """Add ``options`` to every YoutubeDL instance built from now on.

    Replaces what an earlier call set. Keys that affect certificate checks
    are refused, so a platform cannot switch HTTPS verification off.
    """
    global _platform_options
    options = dict(options or {})
    for key in ('nocheckcertificate', 'legacyserverconnect'):
        if key in options:
            raise ValueError(f"'{key}' cannot be set as a platform option")
    _platform_options = options


# Options the user's settings add to every YoutubeDL instance (the proxy);
# see set_network_options.
_network_options = {}

def set_network_options(proxy=''):
    """Send every request through ``proxy`` (a urls.proxy_url address; '' for none)."""
    global _network_options
    _network_options = {'proxy': proxy} if proxy else {}


def network_proxy():
    """The proxy address set with set_network_options ('' for none)."""
    return _network_options.get('proxy', '')


# Settings › Detailed log: yt-dlp writes its debug output (versions, the
# requests it makes, format choices) to the log file too.
_verbose = False


def set_verbose(on):
    global _verbose
    _verbose = bool(on)


# A tiny answer from a site that is reachable nearly everywhere (Settings › Test).
CONNECTION_TEST_URL = 'https://www.youtube.com/generate_204'


def check_connection(proxy='', url=CONNECTION_TEST_URL, timeout=10):
    """Reach ``url`` through ``proxy`` ('' for a direct connection).

    Returns ``(seconds, None)`` when it answered, else ``(None, error)``.
    The certificate is checked as for downloads.
    """
    from yt_dlp.networking import Request
    options = {'quiet': True, 'no_warnings': True, 'color': 'no_color', 'socket_timeout': timeout}
    if proxy:
        options['proxy'] = proxy
    started = time.monotonic()
    try:
        with yt_dlp.YoutubeDL(options) as ydl, ydl.urlopen(Request(url)) as response:
            response.read(1024)
    except Exception as e:
        return None, describe_error(e)
    return time.monotonic() - started, None


class ProxyRequestError(OSError):
    """A request through the proxy failed; ``code`` is the HTTP status, if any."""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class _ProxiedResponse:
    """A yt-dlp response that closes its YoutubeDL with it; network errors are OSError."""

    def __init__(self, ydl, response):
        self._ydl, self._response = ydl, response
        self.headers = response.headers
        self.url = response.url

    def read(self, size=-1):
        from yt_dlp.networking.exceptions import RequestError
        try:
            return self._response.read(None if size is None or size < 0 else size)
        except RequestError as e:
            raise ProxyRequestError(str(e)) from e

    def close(self):
        try:
            self._response.close()
        finally:
            self._ydl.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def open_through_proxy(url, headers=None, timeout=None):
    """Open ``url`` through the proxy set with set_network_options.

    For the app's own requests (update checks), which plain urllib would
    send past an HTTP or SOCKS proxy the user set for downloads. The
    certificate is checked as for downloads.
    """
    from yt_dlp.networking import Request
    from yt_dlp.networking.exceptions import HTTPError, RequestError
    ydl = yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'color': 'no_color',
                            'socket_timeout': timeout or SOCKET_TIMEOUT, **_network_options})
    try:
        response = ydl.urlopen(Request(url, headers=headers or {}))
    except HTTPError as e:
        ydl.close()
        raise ProxyRequestError(str(e), code=e.status) from e
    except RequestError as e:
        ydl.close()
        raise ProxyRequestError(str(e)) from e
    except BaseException:
        ydl.close()
        raise
    return _ProxiedResponse(ydl, response)


# The browser's sign-in (browser_cookies.BrowserSignIn; on Android the app's
# own, AppSignIn) when the user turned it on; see set_reddit_sign_in.
_reddit_sign_in = None

def set_reddit_sign_in(sign_in):
    """Send the browser's cookies of browser_cookies.SITES with every request (None: never)."""
    global _reddit_sign_in
    _reddit_sign_in = sign_in


def base_ydl_options(log_callback=None):
    """Options shared by every YoutubeDL instance.

    HTTPS certificate verification stays on (no ``nocheckcertificate``) and
    messages go through YtDlpLogger rather than being silenced with
    ``quiet``/``no_warnings``.
    """
    return {
        # A copy, because yt-dlp may normalise nested option dicts in place.
        **copy.deepcopy(_platform_options),
        **_network_options,
        # Only the cookies of browser_cookies.SITES, so other sites see no sign-in.
        **(_reddit_sign_in.ydl_options() if _reddit_sign_in else {}),
        'logger': YtDlpLogger(log_callback),
        'noprogress': True,
        # yt-dlp colours messages when stderr is a console (as on Windows),
        # and the escape codes would end up in the UI log and dialogs.
        'color': 'no_color',
        # Give up on a stalled connection instead of hanging forever, and
        # retry transient network errors a bounded number of times.
        'socket_timeout': SOCKET_TIMEOUT,
        'retries': RETRIES,
        'fragment_retries': RETRIES,
        'extractor_retries': 3,
        'file_access_retries': 3,
        **({'verbose': True} if _verbose else {}),
    }


def impersonation_available():
    """True when yt-dlp can impersonate a browser (curl_cffi is installed).

    TikTok's extractor asks for impersonation; without it TikTok often
    answers with a challenge page instead of the video data.
    """
    from yt_dlp.networking.common import _REQUEST_HANDLERS
    from yt_dlp.networking.impersonate import ImpersonateRequestHandler
    return any(issubclass(handler, ImpersonateRequestHandler) and handler.supported_targets
               for handler in _REQUEST_HANDLERS.values())


SOCKET_TIMEOUT = 30
RETRIES = 5

# YouTube answers "Sign in to confirm you're not a bot" to networks it
# distrusts (often mobile data and shared addresses) for yt-dlp's default
# player clients. These clients need no PO token and are often let through;
# a DownloadManager built with ``bot_check_clients`` tries them in order.
BOT_CHECK_CLIENTS = (('tv',), ('web_embedded', 'tv_downgraded'))
# Keys yt-dlp adds when it selects formats. They are dropped before an info
# dict is processed again with another format choice (as --load-info-json does).
_SELECTION_KEYS = ('requested_downloads', 'requested_formats', 'requested_subtitles',
                   'requested_entries', 'filepath', '_filename', 'filename', 'infojson_filename')


def is_bot_check(message):
    """True for YouTube's "Sign in to confirm you're not a bot" refusal."""
    return 'not a bot' in str(message or '').lower()


def with_player_clients(options, clients):
    """``options`` with YouTube's player clients set to ``clients`` (None: unchanged)."""
    if not clients:
        return options
    options = dict(options)
    extractor_args = copy.deepcopy(options.get('extractor_args') or {})
    extractor_args.setdefault('youtube', {})['player_client'] = list(clients)
    options['extractor_args'] = extractor_args
    return options


def reusable_info(info):
    """A copy of an analysed video's info that can be processed again.

    The copy leaves out what the earlier format selection added, so a
    different format choice starts from the full format list.
    """
    info = copy.deepcopy(info)
    for key in _SELECTION_KEYS:
        info.pop(key, None)
    return info


class PartialFiles:
    """Remembers the files a download touched so a cancel or failure can remove them.

    yt-dlp reports its working names through progress hooks; it also leaves
    ``.part``, ``.ytdl`` and ``.part-FragN`` files next to them.

    :meth:`claim` registers the output base name chosen for the item. It was
    free when chosen (see ``filenames.unique_base``), so every file that
    starts with it (thumbnail, ``.fNNN`` format parts, ``.temp`` files)
    belongs to this download. A folder the download created is removed too
    when it is left empty.
    """

    def __init__(self):
        self.paths = set()
        self.bases = set()
        self.folders = []

    def claim(self, base, new_folders=()):
        """Own every file starting with ``base.`` and the folders listed
        (outermost first) that this download created."""
        self.bases.add(base)
        self.folders.extend(new_folders)

    def track(self, d):
        for key in ('tmpfilename', 'filename'):
            if d.get(key):
                self.paths.add(d[key])

    def cleanup(self):
        removed = []
        for path in self.paths:
            folder = os.path.dirname(path) or '.'
            name = os.path.basename(path)
            candidates = {path, path + '.part', path + '.ytdl'}
            if os.path.isdir(folder):
                candidates.update(
                    os.path.join(folder, f) for f in os.listdir(folder)
                    if f.startswith(name + '.part-Frag') or f.startswith(name + '-Frag'))
            for candidate in candidates:
                try:
                    os.remove(candidate)
                    removed.append(candidate)
                except FileNotFoundError:
                    pass
                except OSError as e:
                    _log.warning("Could not remove partial file %s: %s", candidate, e)
        for base in self.bases:
            folder, prefix = os.path.dirname(base) or '.', os.path.basename(base) + '.'
            if not os.path.isdir(folder):
                continue
            for f in os.listdir(folder):
                path = os.path.join(folder, f)
                if f.startswith(prefix) and os.path.isfile(path):
                    try:
                        os.remove(path)
                        removed.append(path)
                    except OSError as e:
                        _log.warning("Could not remove partial file %s: %s", path, e)
        for folder in reversed(self.folders):
            try:
                os.rmdir(folder)  # only succeeds when empty
            except OSError:
                pass
        return removed


_ANSI_RE = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')


def strip_ansi(text):
    """Remove terminal colour codes such as '\x1b[0;31m'."""
    return _ANSI_RE.sub('', str(text))


def describe_error(exc):
    """Readable message for a yt-dlp or other exception, without yt-dlp's 'ERROR: ' prefix."""
    msg = strip_ansi(exc).strip()
    if msg.startswith('ERROR: '):
        msg = msg[len('ERROR: '):]
    return msg or type(exc).__name__


_NUMBER_RE = re.compile(r'^\d+(\.\d+)?$')


class TrimError(ValueError):
    """Trim zaman aralığı geçersiz olduğunda fırlatılır."""


def parse_timestamp(text):
    """
    'SS', 'SS.ms', 'MM:SS' veya 'HH:MM:SS[.ms]' biçimindeki zamanı saniyeye çevirir.
    Boş değer için None döner; geçersiz biçimde TrimError fırlatır.
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None

    parts = text.split(':')
    if len(parts) > 3:
        raise TrimError(f"Invalid time '{text}': use SS, MM:SS or HH:MM:SS")
    # Sadece son parça ondalıklı olabilir
    for i, part in enumerate(parts):
        is_last = i == len(parts) - 1
        if not (_NUMBER_RE.match(part) if is_last else part.isdigit()):
            raise TrimError(f"Invalid time '{text}': use SS, MM:SS or HH:MM:SS")

    values = [float(part) for part in parts]
    # İlk parça dışındakiler (dakika/saniye) 60'tan küçük olmalı
    if any(v >= 60 for v in values[1:]):
        raise TrimError(f"Invalid time '{text}': minutes and seconds must be below 60")

    seconds = 0.0
    for v in values:
        seconds = seconds * 60 + v
    return seconds


def parse_trim_range(start_text, end_text, duration=None):
    """
    Trim başlangıç/bitiş metnini doğrulanmış (start, end) saniye çiftine çevirir.
    İkisi de boşsa None döner (kırpma yok). Başlangıç boşsa 0, bitiş boşsa
    video sonu (duration bilinmiyorsa sonsuz) kabul edilir.
    Kurallar: 0 <= start < end ve duration biliniyorsa end <= duration.
    """
    start = parse_timestamp(start_text)
    end = parse_timestamp(end_text)
    if start is None and end is None:
        return None
    if start is None:
        start = 0.0
    if end is None:
        end = float(duration) if duration else float('inf')

    if duration:
        if start >= duration:
            raise TrimError(f"Trim start ({start:g}s) is beyond the video length ({duration:g}s)")
        if end > duration:
            raise TrimError(f"Trim end ({end:g}s) is beyond the video length ({duration:g}s)")
    if start >= end:
        raise TrimError(f"Trim start ({start:g}s) must be before end ({end:g}s)")
    return start, end


class DownloadManager:
    def __init__(self, tools=None, bot_check_clients=()):
        # media_tools.ToolStatus; None means "detect on first download".
        self.tools = tools
        # Player clients to retry YouTube with when it asks to confirm this
        # is not a bot (see BOT_CHECK_CLIENTS); empty keeps yt-dlp's choice.
        self.bot_check_clients = tuple(bot_check_clients)
        # The clients that last got past the check, tried first from then on.
        self._working_clients = None

    def _client_attempts(self):
        """YouTube player clients to try in order; None means yt-dlp's default."""
        attempts = [None, *self.bot_check_clients]
        if self._working_clients in attempts:
            attempts.remove(self._working_clients)
            attempts.insert(0, self._working_clients)
        return attempts

    def _retry_bot_check(self, message, clients, attempts, log_callback):
        """Whether to try the next player clients after ``message``."""
        position = attempts.index(clients)
        if not is_bot_check(message) or position + 1 >= len(attempts):
            return False
        following = attempts[position + 1]
        if log_callback:
            log_callback("YouTube asked to confirm this is not a bot; trying its "
                         f"{'/'.join(following) if following else 'default'} player")
        return True

    def _extract(self, url, ydl_opts, log_callback):
        """``extract_info`` with the bot-check retries; returns (info, clients)."""
        attempts = self._client_attempts()
        for clients in attempts:
            try:
                with yt_dlp.YoutubeDL(with_player_clients(ydl_opts, clients)) as ydl:
                    info = ydl.extract_info(url, download=False)
            except Exception as e:
                if self._retry_bot_check(describe_error(e), clients, attempts, log_callback):
                    continue
                raise
            self._working_clients = clients
            return info, clients

    def ensure_tools(self):
        """FFmpeg/ffprobe status, detected (and put on PATH) on first use."""
        if self.tools is None:
            self.tools = media_tools.find_tools()
            media_tools.activate(self.tools)
            deno = shutil.which("deno")
            if deno:
                _log.info("JavaScript runtime for YouTube: %s", deno)
            else:
                _log.warning("No Deno found; yt-dlp may offer fewer YouTube formats")
            if impersonation_available():
                _log.info("Browser impersonation (curl_cffi) is available")
            else:
                _log.warning("curl_cffi is missing; TikTok and some other sites may refuse downloads")
        return self.tools

    def fetch_info(self, url, log_callback=None, cancel_event=None, progress=None):
        """ 
        Playlist veya video bilgisini çeker.
        Hata olursa None döndürmez, 'error' ve 'error_type' anahtarları olan bir sözlük döndürür.

        Setting ``cancel_event`` stops the analysis at the next page yt-dlp
        (or the Spotify reader) asks for; the result is then
        ``{'error': 'Cancelled by user', 'cancelled': True}``.

        ``progress(count, total)`` is called while a playlist's entries are
        read (``total`` is None when the site does not say), at most every
        PROGRESS_EVERY entries.
        """
        cancelled = {'error': 'Cancelled by user', 'error_type': 'DownloadCancelled', 'cancelled': True}

        def is_cancelled():
            return cancel_event is not None and cancel_event.is_set()

        def read_page(page, headers=None, data=None):
            if is_cancelled():
                raise yt_dlp.utils.DownloadCancelled('Cancelled by user')
            return _read_page(page, ydl_opts, headers, data)

        ydl_opts = base_ydl_options(log_callback)
        try:
            info = spotify.fetch_info(url, read_page)
        except Exception as e:
            if is_cancelled():
                return cancelled
            return {'error': describe_error(e), 'error_type': type(e).__name__}
        if is_cancelled():
            return cancelled
        if info is not None:  # a Spotify song or list: songs to search for on YouTube
            if info.get('partial'):
                message = f"Spotify: only the first {spotify.EMBED_LIMIT} songs could be read ({info['partial']})"
                _log.warning(message)
                if log_callback:
                    log_callback(message)
            return info
        ydl_opts['extract_flat'] = True
        # Playlist analysis tolerates individual unavailable entries; yt-dlp
        # still reports them through the logger, so they are not silent.
        ydl_opts['ignoreerrors'] = True

        attempts = self._client_attempts()
        for clients in attempts:
            logger = YtDlpLogger(log_callback, cancel_event)
            ydl_opts['logger'] = logger
            try:
                with yt_dlp.YoutubeDL(with_player_clients(ydl_opts, clients)) as ydl:
                    if progress is None:
                        info = ydl.extract_info(url, download=False)
                    else:
                        # The same as extract_info(), with the playlist's entries
                        # counted as yt-dlp reads them page by page.
                        info = ydl.extract_info(url, download=False, process=False)
                        if info is not None:
                            info = ydl.process_ie_result(counting_entries(info, progress, is_cancelled),
                                                         download=False)
            except Exception as e:
                if is_cancelled():
                    return cancelled
                if self._retry_bot_check(describe_error(e), clients, attempts, log_callback):
                    continue
                return {'error': explain_site_error(describe_error(e)), 'error_type': type(e).__name__}

            if is_cancelled():
                return cancelled
            if info is None:
                # ignoreerrors turned the failure into None; keep yt-dlp's reason.
                reason = logger.errors[-1] if logger.errors else 'Content is private or unavailable'
                if self._retry_bot_check(reason, clients, attempts, log_callback):
                    continue
                return {'error': explain_site_error(reason), 'error_type': 'DownloadError'}
            self._working_clients = clients
            return info

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None, cancel_event=None,
                       info=None, pause_event=None):
        """Download one item and return its :class:`results.ItemResult`.

        Never raises for download problems: yt-dlp, trim and postprocessor
        errors all become a ``failed`` result with a readable message, and a
        result is only ``completed`` when the output file exists and is not
        empty.

        Works in two phases. A metadata pass selects the formats (and gives
        the title and duration); the download pass then runs with options
        that depend on that selection: the trim range, and whether the
        container can be reached by remuxing or needs re-encoding.

        Setting ``cancel_event`` stops the download at the next progress
        update; the item is then ``cancelled``. Partial files are removed
        for cancelled and failed items alike.

        While ``pause_event`` is set the download waits at its next progress
        update (see :func:`wait_while_paused`); Cancel still works.

        ``info`` is what :meth:`fetch_info` returned for this very video. The
        metadata pass then selects formats from it instead of asking the site
        again, which saves a round of requests (and, for YouTube, solving
        its JavaScript challenge once more).
        """
        title = title or url
        partial = PartialFiles()
        resumable = []  # the base name whose partial files a later try can continue (resume.py)
        postprocessing = []  # set once the download is in (or past) its postprocessing

        def remove_partial_files():
            removed = partial.cleanup()
            if removed and log_callback:
                log_callback(f"Removed {len(removed)} partial file(s)")

        def failed(error):
            # A download that failed after data arrived keeps its partial
            # files, so trying the same video again continues it
            # (resume.py). Anything else leaves nothing behind: parts that
            # cannot be continued would only fill the disk.
            # A failed conversion or merge would only fail again.
            in_download = not postprocessing and not str(error).startswith('Postprocessing')
            if resumable and in_download and not is_cancelled() and resume.has_partial_data(resumable[0]):
                if log_callback:
                    log_callback("Kept the partial download; downloading this video again continues it")
                return ItemResult(url, title, ItemStatus.FAILED, error=error)
            remove_partial_files()
            return ItemResult(url, title, ItemStatus.FAILED, error=error)

        def cancelled():
            remove_partial_files()
            return ItemResult(url, title, ItemStatus.CANCELLED, error='Cancelled by user')

        def is_cancelled():
            return cancel_event is not None and cancel_event.is_set()

        def check_cancel(d=None):
            if d is not None:
                partial.track(d)
            wait_while_paused(pause_event, cancel_event)
            if is_cancelled():
                raise yt_dlp.utils.DownloadCancelled('Cancelled by user')

        def on_progress(d):
            check_cancel(d)
            if progress_hook:
                progress_hook(d)

        def on_postprocess(d):
            postprocessing.append(True)
            check_cancel()
            if progress_hook:
                progress_hook(d)

        wait_while_paused(pause_event, cancel_event)
        if is_cancelled():
            return ItemResult(url, title, ItemStatus.CANCELLED, error='Cancelled by user')

        mode = options.get('mode', formats.VIDEO_AUDIO)
        quality = options.get('quality', 'Best')
        try:
            plan = formats.build_format_plan(mode, options.get('format', 'mp4'), quality)
            # Validate the trim text before any network access.
            trim_requested = parse_trim_range(options.get('trim_start'), options.get('trim_end')) is not None
        except (formats.FormatError, TrimError) as e:
            return failed(str(e))

        base_folder = options.get('save_path', os.getcwd())
        tools = self.ensure_tools()
        if not tools.ok:
            return failed(tools.error)

        # A failed download must raise, so it becomes a failed result
        # instead of being reported as finished (no 'ignoreerrors').
        ydl_opts = base_ydl_options(log_callback)
        ydl_opts.update({
            # Collision-safe names are only known after the metadata pass;
            # this placeholder is never written to.
            'outtmpl': os.path.join(filenames.escape_template(base_folder), '%(title)s.%(ext)s'),
            'windowsfilenames': True,
            'overwrites': False,
            'ffmpeg_location': tools.directory,
            'progress_hooks': [on_progress],
            # Postprocessing (merge, conversion) can take a while too; the
            # progress hook also sees these so the UI can show the stage.
            'postprocessor_hooks': [on_postprocess],
        })
        ydl_opts.update(plan.options)
        # Speed settings (settings.download_speed_options); nothing else from
        # ``options`` reaches yt-dlp directly.
        for key in SPEED_OPTIONS:
            if options.get(key):
                ydl_opts[key] = options[key]
        meta = options.get('meta') or {}

        try:
            # Phase 1: metadata and format selection, no download.
            if info is not None:
                with yt_dlp.YoutubeDL(dict(ydl_opts)) as ydl:
                    info = ydl.process_ie_result(reusable_info(info), download=False)
            else:
                target = url
                if url.startswith(playlist.SEARCH_PREFIX) and meta.get('duration'):
                    target = self._closest_result(url, meta['duration'], log_callback) or url
                check_cancel()
                info, _clients = self._extract(target, dict(ydl_opts), log_callback)
            if info is not None and info.get('_type') == 'playlist':
                # A search (Spotify songs: "ytsearch1:...") gives a list of one result.
                info = next(iter(info.get('entries') or []), None)
            if info is None:
                return failed('No media information returned')
            if meta:
                apply_song_meta(info, meta)
            title = info.get('title') or title
            if plan.needs_audio and not formats.has_audio(info):
                return failed('This media has no audio track')
            if log_callback:
                log_callback(f"Format: {formats.describe_selection(info)} -> {plan.ext}")
                if formats.height_unknown(info) and formats.VIDEO_QUALITIES.get(quality):
                    log_callback(f"Warning: this source does not report its resolution; "
                                 f"the {quality} limit may not apply")

            check_cancel()
            # Phase 2: download with options that depend on the selection.
            folder = filenames.output_folder(base_folder, info, options.get('playlist_title'))
            # The chosen download folder is never removed; only the
            # platform or playlist folders made for this item can be.
            os.makedirs(base_folder, exist_ok=True)
            new_folders = _missing_folders(folder)
            os.makedirs(folder, exist_ok=True)
            ydl_opts['outtmpl'] = filenames.output_template(folder, options.get('playlist_index'))
            with yt_dlp.YoutubeDL(dict(ydl_opts)) as ydl:
                prepared = ydl.prepare_filename(info)
            # A cut (trim) or a live stream is downloaded by FFmpeg, which cannot continue a file.
            ident = None if trim_requested or info.get('is_live') else resume.identity(info, plan.ext, mode)
            base = resume.find(folder, ident)  # also clears partial downloads left too long
            if base is not None:
                if log_callback:
                    log_callback(f"Continuing the unfinished download of {os.path.basename(base)}.{plan.ext}")
            else:
                base = filenames.unique_base(prepared, plan.ext)
                if base != os.path.splitext(prepared)[0] and log_callback:
                    log_callback(f"File exists; saving as {os.path.basename(base)}.{plan.ext}")
            partial.claim(base, new_folders)
            if ident is not None and resume.save(base, ident):
                resumable.append(base)
            ydl_opts['outtmpl'] = filenames.escape_template(base) + '.%(ext)s'
            ydl_opts['postprocessors'] = formats.postprocessors_for(plan, info)
            if ydl_opts.get('http_chunk_size') and not plain_http_download(info):
                # yt-dlp applies the chunk size to the byte-range segments
                # of HLS/DASH streams too, takes each finished segment for
                # an unfinished chunk of the whole file and gives up with
                # "Conflicting range" (Reddit's videos). Chunks only help
                # plain HTTP files anyway.
                del ydl_opts['http_chunk_size']
            if trim_requested:
                if not info.get('duration') and log_callback:
                    log_callback("Warning: this source does not report its length; "
                                 "the trim end cannot be checked in advance")
                trim_range = parse_trim_range(
                    options.get('trim_start'), options.get('trim_end'), info.get('duration'))
                # yt-dlp (start, end) çiftleri bekler
                ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [trim_range])
                ydl_opts['force_keyframes_at_cuts'] = True
            sponsorblock = bool(options.get('sponsorblock'))
            categories = formats.sponsorblock_categories(options.get('sponsorblock_categories'))
            if sponsorblock and not categories:
                sponsorblock = False
                if log_callback:
                    log_callback("SponsorBlock: no categories chosen in Settings")
            if sponsorblock:
                ydl_opts['postprocessors'] = formats.with_sponsor_cuts(ydl_opts['postprocessors'], categories,
                                                                    exact=trim_requested)
            if options.get('live_from_start') and info.get('is_live'):
                ydl_opts['live_from_start'] = True
            selected = reusable_info(info) if options.get('subtitles') and mode != formats.AUDIO_ONLY else None
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if sponsorblock:
                    ydl.add_post_processor(QuietSponsorBlockPP(ydl, categories=categories), when='after_filter')
                if trim_requested:
                    # Chapters and SponsorBlock segments are times in the whole
                    # video; the trimmed file starts at the trim start.
                    ydl.add_post_processor(SectionChaptersPP(ydl), when='before_dl')
                if plan.strip_audio:
                    ydl.add_post_processor(StripAudioPP(ydl), when='post_process')
                info = ydl.process_ie_result(info, download=True)
                if info is None:
                    return failed('No media information returned')
                path = final_output_path(ydl, info)
        except TrimError as e:
            return failed(str(e))
        except Exception as e:
            if is_cancelled():
                return cancelled()
            return failed(explain_site_error(explain_format_error(describe_error(e), mode, quality)))

        # The file exists and is not empty; ffprobe proves it can be read
        # and holds what the mode promises.
        problem = verify_output(path) or probe_output(
            path, tools.ffprobe, need_video=mode != formats.AUDIO_ONLY, need_audio=mode == formats.AUDIO_ONLY)
        if problem:
            resumable.clear()  # a broken result is not worth continuing
            return failed(problem)
        if resumable:
            resume.forget(resumable[0])
        if selected is not None and not is_cancelled():
            saved = self._download_subtitles(selected, base, options.get('subtitle_langs'), tools, log_callback,
                                             options.get('subtitle_format') or 'srt')
            if saved and options.get('subtitle_embed'):
                embed_subtitles(path, [sub['filepath'] for sub in saved], tools.ffmpeg, log_callback)
        return ItemResult(url, title, ItemStatus.COMPLETED, path=path)

    def _closest_result(self, url, duration, log_callback=None):
        """The link of the search result whose length is closest to ``duration``.

        ``url`` is a "ytsearch1:" search for a song (spotify.py). The first
        few results are compared, so a music video with a long intro or a
        live version loses to the plain song. None when the search fails.
        """
        query = SEARCH_CANDIDATES_PREFIX + url[len(playlist.SEARCH_PREFIX):]
        ydl_opts = base_ydl_options(log_callback)
        ydl_opts['extract_flat'] = 'in_playlist'
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                found = ydl.extract_info(query, download=False) or {}
        except Exception as e:
            _log.warning("Search for %s failed: %s", url, describe_error(e))
            return None
        entry = closest_by_duration(list(found.get('entries') or []), duration)
        return playlist.entry_url(entry) if entry else None

    def _download_subtitles(self, info, base, langs, tools, log_callback=None, fmt='srt'):
        """Save the subtitles of a downloaded video next to it as files of ``fmt``
        (one of SUBTITLE_FORMATS: srt, ass or vtt).

        A separate pass after the video is saved: a missing or refused
        subtitle (YouTube often limits them) never costs the video itself.
        """
        fmt = fmt if fmt in SUBTITLE_FORMATS else 'srt'
        langs = [f'{lang}.*' for lang in (langs or ['en'])]
        ydl_opts = base_ydl_options(log_callback)
        ydl_opts.update({
            'skip_download': True,
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': langs,
            'subtitlesformat': f'{fmt}/srt/vtt/best',
            'outtmpl': filenames.escape_template(base) + '.%(ext)s',
            'ffmpeg_location': tools.directory,
            'postprocessors': [{'key': 'FFmpegSubtitlesConvertor', 'format': fmt, 'when': 'before_dl'}],
            # Subtitle problems become warnings instead of errors.
            'ignoreerrors': True,
        })
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.process_ie_result(info, download=True) or {}
        except Exception as e:
            result = {}
            _log.warning("Subtitles failed: %s", describe_error(e))
        saved = [sub for sub in (result.get('requested_subtitles') or {}).values() if sub.get('filepath')]
        if log_callback:
            log_callback(f"Subtitles: {len(saved)} saved" if saved else "Subtitles: none available")
        return saved


PAGE_ATTEMPTS = 3
PAUSE_POLL_SECONDS = 0.2
PROGRESS_EVERY = 25  # playlist entries between analysis progress reports


def counting_entries(info, progress, is_cancelled=lambda: False):
    """``info`` (an unprocessed playlist) with its entries reported to
    ``progress(count, total)`` as they are read, every PROGRESS_EVERY.

    Only entries read one after another (a generator, as most sites give)
    are counted; a list or a paged list is read in other ways and is left
    as it is. A cancel stops the reading at the next entry.
    """
    entries = info.get('entries')
    if info.get('_type') != 'playlist' or entries is None or isinstance(entries, (list, tuple)) \
            or isinstance(entries, yt_dlp.utils.PagedList):
        return info
    total = info.get('playlist_count') if isinstance(info.get('playlist_count'), int) else None

    def read():
        count = 0
        for entry in entries:
            if is_cancelled():
                raise yt_dlp.utils.DownloadCancelled('Cancelled by user')
            count += 1
            if count % PROGRESS_EVERY == 0:
                progress(count, total)
            yield entry
        progress(count, total)
    return {**info, 'entries': read()}


def wait_while_paused(pause_event, cancel_event=None):
    """Block while ``pause_event`` is set, until it is cleared or ``cancel_event`` is set.

    Called from yt-dlp's progress hooks, so a paused download stops reading
    from the site. If the site drops the idle connection meanwhile, yt-dlp
    reconnects on resume and asks for the rest of the file (its ``.part``
    is kept), or goes on with the next fragment of a stream.
    """
    while pause_event is not None and pause_event.is_set():
        if cancel_event is not None and cancel_event.is_set():
            return
        time.sleep(PAUSE_POLL_SECONDS)


def _read_page(url, ydl_opts, headers=None, data=None):
    """``(final url, text)`` of a web page, fetched with yt-dlp's networking (POST with ``data``).

    A connection cut off mid-page ("17388 bytes read") is tried again; an
    HTTP error answer is not.
    """
    from http.client import IncompleteRead as HttpIncompleteRead
    from yt_dlp.networking import Request
    from yt_dlp.networking.exceptions import HTTPError, IncompleteRead, TransportError
    for attempt in range(PAGE_ATTEMPTS):
        try:
            with yt_dlp.YoutubeDL(dict(ydl_opts)) as ydl:
                with ydl.urlopen(Request(url, data=data, headers=headers or {})) as response:
                    return response.url, response.read().decode('utf-8', 'replace')
        except HTTPError:
            raise
        except (IncompleteRead, HttpIncompleteRead, TransportError) as e:
            if attempt + 1 == PAGE_ATTEMPTS:
                raise
            _log.warning("Reading %s failed (%s); trying again", url, describe_error(e))


def plain_http_download(info):
    """True when every selected format of ``info`` is a single HTTP(S) file."""
    selected = info.get('requested_formats') or [info]
    return all(f.get('protocol') in ('http', 'https') for f in selected)


# Download options a caller may pass through download_video's ``options``.
SPEED_OPTIONS = ('concurrent_fragment_downloads', 'http_chunk_size', 'ratelimit')

# How many search results are compared for a song (DownloadManager._closest_result),
# and how far (seconds) the first result's length may be off before another wins.
SEARCH_CANDIDATES_PREFIX = 'ytsearch3:'
CLOSE_ENOUGH_SECONDS = 15


# Subtitle file types offered in Settings (FFmpeg converts to each).
SUBTITLE_FORMATS = ('srt', 'ass', 'vtt')
_SUBTITLE_LANGUAGE = re.compile(r'^[a-z]{2,3}(-[a-z0-9]{2,8})*$', re.I)


def subtitle_languages(language, chosen=''):
    """Subtitle languages to save.

    ``chosen`` is the Settings text ("en, tr, pt-BR"); when it is empty the
    app's language ``language`` is used, then English. Unusable entries are
    left out.
    """
    picked = [part.strip() for part in re.split(r'[,;\s]+', chosen or '') if part.strip()]
    picked = [lang for lang in picked if _SUBTITLE_LANGUAGE.match(lang)]
    if picked:
        return list(dict.fromkeys(picked))
    langs = [language or 'en', *(['no'] if language == 'nb' else []), 'en']
    return list(dict.fromkeys(langs))


# Subtitle codecs each video container takes; MKV keeps the files' own format.
_EMBEDDED_SUBTITLE_CODECS = {'mp4': 'mov_text', 'webm': 'webvtt', 'mkv': 'copy'}


def embed_subtitles(video, subtitles, ffmpeg, log_callback=None, run=None):
    """Put the subtitle files into ``video`` as subtitle tracks, then delete them.

    The language of each track comes from its name ("Video.en.srt"). When
    FFmpeg fails, the video stays as it was and the files stay next to it.
    Returns True when the subtitles are inside the video.
    """
    import subprocess
    run = run or subprocess.run
    ext = os.path.splitext(video)[1].lstrip('.').lower()
    codec = _EMBEDDED_SUBTITLE_CODECS.get(ext)
    if codec is None or not subtitles or not ffmpeg:
        return False
    if ext == 'mkv' and any(sub.lower().endswith('.vtt') for sub in subtitles):
        codec = 'srt'  # older players read SRT in MKV better than WebVTT
    temp = yt_dlp.utils.prepend_extension(video, 'subs-temp')
    command = [ffmpeg, '-y', '-loglevel', 'error', '-i', video]
    for sub in subtitles:
        command += ['-i', sub]
    command += ['-map', '0', '-map', '-0:s']
    for i in range(len(subtitles)):
        command += ['-map', f'{i + 1}:0']
    command += ['-c', 'copy', '-c:s', codec]
    for i, sub in enumerate(subtitles):
        lang = os.path.basename(sub).rsplit('.', 2)[-2] if sub.count('.') >= 2 else ''
        long = yt_dlp.utils.ISO639Utils.short2long(lang.split('-')[0]) or lang
        if long:
            command += [f'-metadata:s:s:{i}', f'language={long}']
    if ext == 'mp4':
        command += ['-movflags', '+faststart']
    command.append(temp)
    flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0) if os.name == 'nt' else 0
    try:
        proc = run(command, capture_output=True, text=True, timeout=600, creationflags=flags)
        ok = proc.returncode == 0 and os.path.isfile(temp) and os.path.getsize(temp) > 0
        if not ok:
            raise OSError((proc.stderr or '').strip()[-300:] or f'exit code {proc.returncode}')
        os.replace(temp, video)
    except (OSError, subprocess.SubprocessError) as e:
        _log.warning("Could not put the subtitles into %s: %s", video, e)
        try:
            os.remove(temp)
        except OSError:
            pass
        if log_callback:
            log_callback("Subtitles: could not be put into the video; they are saved next to it")
        return False
    for sub in subtitles:
        try:
            os.remove(sub)
        except OSError:
            pass
    if log_callback:
        log_callback(f"Subtitles: {len(subtitles)} put into the video")
    return True


def closest_by_duration(entries, duration):
    """The entry to download for a song ``duration`` seconds long, or None.

    The first result is kept when its length is close; otherwise the result
    whose length is closest wins (results without a length never do).
    """
    entries = [e for e in entries if e and playlist.entry_url(e)]
    if not entries:
        return None
    timed = [e for e in entries if isinstance(e.get('duration'), (int, float))]
    first = entries[0]
    if first in timed and abs(first['duration'] - duration) <= CLOSE_ENOUGH_SECONDS:
        return first
    if not timed:
        return first
    return min(timed, key=lambda e: abs(e['duration'] - duration))


def apply_song_meta(info, meta):
    """Put a song's names and cover (spotify.py) into the info of its YouTube video.

    The file is then named "Artist - Track", its tags name the song rather
    than the video and the cover embedded is the album's.
    """
    artist, track = meta.get('artist'), meta.get('track')
    if track:
        info['title'] = f'{artist} - {track}' if artist else track
        info['track'] = track
    if artist:
        info['artist'] = artist
        info['artists'] = [artist]
        info['creators'] = [artist]
    if meta.get('album'):
        info['album'] = meta['album']
    if meta.get('cover'):
        info['thumbnails'] = [{'url': meta['cover'], 'id': 'cover'}]
        info['thumbnail'] = meta['cover']
    return info

def _missing_folders(folder):
    """``folder`` and its parents that do not exist yet, outermost first."""
    missing = []
    while folder and not os.path.exists(folder):
        missing.append(folder)
        parent = os.path.dirname(folder)
        if parent == folder:
            break
        folder = parent
    return list(reversed(missing))


# Shown instead of yt-dlp's "Account authentication is required ... --cookies"
# for Reddit, which only shows NSFW posts to signed-in accounts.
REDDIT_SIGN_IN_OFF = ('Reddit shows this post only to signed-in accounts (often NSFW). Turn on the '
                      'browser sign-in in Settings, then try again')
REDDIT_SIGN_IN_MISSING = ('Reddit shows this post only to signed-in accounts. Sign in to Reddit in '
                          'Firefox or Zen, allow mature content in your Reddit settings, then try again')


# The same for the other sites of browser_cookies.SITES ("{site}" is filled in).
SIGN_IN_OFF = ('{site} shows this only to signed-in accounts. Turn on the browser sign-in in Settings, '
               'then try again')
SIGN_IN_MISSING = '{site} shows this only to signed-in accounts. Sign in to {site} in Firefox or Zen, then try again'

# yt-dlp's extractor tags and the words of a sign-in refusal on each site.
_SIGN_IN_REFUSALS = (
    ('Reddit', ('[reddit]',), ('account authentication is required',)),
    ('Instagram', ('[instagram',), ('login required', 'log in', '--cookies')),
    ('YouTube', ('[youtube]',), ('sign in to confirm your age', 'inappropriate for some users')),
    ('Facebook', ('[facebook',), ('login', '--cookies')),
    ('X', ('[twitter',), ('login', 'log in', '--cookies', 'nsfw')),
    ('TikTok', ('[tiktok',), ('log in', 'login', '--cookies')),
)


def sign_in_site(message):
    """The site (of browser_cookies.SITES) that refused ``message`` for want of a sign-in, or None."""
    text = str(message or '').lower()
    for site, tags, words in _SIGN_IN_REFUSALS:
        if any(tag in text for tag in tags) and any(word in text for word in words):
            return site
    return None


def sign_in_offer(message):
    """The site a sign-in would help with for ``message`` (an explain_site_error text), or None."""
    if message in (REDDIT_SIGN_IN_OFF, REDDIT_SIGN_IN_MISSING):
        return 'Reddit'
    for site in browser_cookies.SITES:
        if message in (SIGN_IN_OFF.format(site=site), SIGN_IN_MISSING.format(site=site)):
            return site
    return None


def explain_site_error(message):
    """Replace yt-dlp's command-line advice for a sign-in refusal with what to do in the app."""
    site = sign_in_site(message)
    if site is None:
        return message
    _log.warning("%s refused without sign-in: %s", site, message)
    if _reddit_sign_in is not None and _reddit_sign_in.signed_in(site):
        return message  # signed in and still refused: keep yt-dlp's reason
    if site == 'Reddit':
        return REDDIT_SIGN_IN_OFF if _reddit_sign_in is None else REDDIT_SIGN_IN_MISSING
    return (SIGN_IN_OFF if _reddit_sign_in is None else SIGN_IN_MISSING).format(site=site)


def explain_format_error(message, mode, quality):
    """Turn yt-dlp's generic 'format is not available' into what it means here."""
    if 'Requested format is not available' not in message:
        return message
    if mode == formats.AUDIO_ONLY:
        return 'This media has no audio track to extract'
    if quality and quality != 'Best':
        return f'No {quality} or lower version of this video is available; try a higher quality'
    return 'No downloadable video format is available for this media'


class QuietSponsorBlockPP(SponsorBlockPP):
    """Looks up a YouTube video's SponsorBlock segments (cut later by ModifyChapters).

    The segments come from sponsor.ajay.app; when that site cannot be
    reached the video is saved uncut instead of failing.
    """

    def run(self, info):
        try:
            return super().run(info)
        except Exception as e:
            self.report_warning(f"SponsorBlock is unavailable, the video is not cut: {e}")
            return [], info


def shift_chapters(chapters, start, end):
    """``chapters`` (start_time/end_time in the whole video) as times in the part from ``start`` to ``end``.

    Chapters outside the part are left out and the others are cut at its
    edges, so a trimmed file gets the chapters (and SponsorBlock segments)
    it really has.
    """
    shifted = []
    for chapter in chapters or []:
        first = max(float(chapter.get('start_time') or 0), start)
        last = min(float(chapter.get('end_time') if chapter.get('end_time') is not None else end), end)
        if last - first > 0.05:
            shifted.append({**chapter, 'start_time': round(first - start, 3), 'end_time': round(last - start, 3)})
    return shifted


class SectionChaptersPP(PostProcessor):
    """For a trimmed download: chapters, SponsorBlock segments and length of the part downloaded.

    yt-dlp keeps the whole video's chapters and length for a time range, so
    ModifyChapters would cut the wrong places and the file would name
    chapters it does not have. Runs before the download, once the part is known.
    """

    def run(self, info):
        start = float(info.get('section_start') or 0)
        end = info.get('section_end') or info.get('duration')
        # A source that does not report its length is cut to its end.
        end = float(end) if end is not None else float('inf')
        if info.get('chapters'):
            info['chapters'] = shift_chapters(info['chapters'], start, end) or None
        if info.get('sponsorblock_chapters'):
            info['sponsorblock_chapters'] = shift_chapters(info['sponsorblock_chapters'], start, end)
        if end != float('inf'):
            info['duration'] = round(end - start, 3)
        return [], info


class StripAudioPP(FFmpegPostProcessor):
    """Removes audio tracks from the final file (Video Only mode).

    Needed when a site only offers files with audio muxed in; for pure video
    streams it does nothing.
    """

    def run(self, info):
        path = info['filepath']
        if info.get('acodec') == 'none':
            return [], info
        temp = yt_dlp.utils.prepend_extension(path, 'temp')
        self.to_screen(f'Removing audio from "{path}"')
        self.run_ffmpeg(path, temp, ['-map', '0', '-map', '-0:a', '-c', 'copy'])
        os.replace(temp, path)
        info['acodec'] = 'none'
        return [], info


def final_output_path(ydl, info):
    """Path of the finished file after merging and postprocessing.

    yt-dlp records it in ``requested_downloads[-1]['filepath']``; the
    prepared filename is only a fallback because conversions change it.
    """
    downloads = info.get('requested_downloads') or []
    for entry in reversed(downloads):
        if entry.get('filepath'):
            return entry['filepath']
    return info.get('filepath') or ydl.prepare_filename(info)
