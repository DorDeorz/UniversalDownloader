import logging
import os
import re
import shutil
import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

import filenames
import formats
import media_tools
from results import ItemResult, ItemStatus, verify_output

_log = logging.getLogger(__name__)
_log.addHandler(logging.NullHandler())


class YtDlpLogger:
    """Routes yt-dlp messages to a callback instead of hiding them.

    yt-dlp calls debug/info/warning/error on this object. Warnings and
    errors go to ``log_callback`` (e.g. the UI log) and to the module
    logger; debug/info chatter only goes to the module logger.
    """

    def __init__(self, log_callback=None):
        self.log_callback = log_callback
        self.errors = []

    def _emit(self, level, prefix, msg):
        msg = strip_ansi(msg)
        _log.log(level, msg)
        if self.log_callback is not None:
            self.log_callback(f"{prefix}{msg}")

    def debug(self, msg):
        # yt-dlp routes its normal screen output through debug() as well.
        _log.debug(msg)

    def info(self, msg):
        _log.info(msg)

    def warning(self, msg):
        self._emit(logging.WARNING, "Warning: ", msg)

    def error(self, msg):
        self.errors.append(describe_error(msg))
        self._emit(logging.ERROR, "", msg)


def base_ydl_options(log_callback=None):
    """Options shared by every YoutubeDL instance.

    HTTPS certificate verification stays on (no ``nocheckcertificate``) and
    messages go through YtDlpLogger rather than being silenced with
    ``quiet``/``no_warnings``.
    """
    return {
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


class PartialFiles:
    """Remembers the files a download touched so a cancel can remove them.

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
    def __init__(self, tools=None):
        # media_tools.ToolStatus; None means "detect on first download".
        self.tools = tools

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

    def fetch_info(self, url, log_callback=None):
        """ 
        Playlist veya video bilgisini çeker.
        Hata olursa None döndürmez, 'error' ve 'error_type' anahtarları olan bir sözlük döndürür.
        """
        ydl_opts = base_ydl_options(log_callback)
        ydl_opts['extract_flat'] = True
        # Playlist analysis tolerates individual unavailable entries; yt-dlp
        # still reports them through the logger, so they are not silent.
        ydl_opts['ignoreerrors'] = True
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info is None:
                    # ignoreerrors turned the failure into None; keep yt-dlp's reason.
                    errors = ydl_opts['logger'].errors
                    reason = errors[-1] if errors else 'Content is private or unavailable'
                    return {'error': reason, 'error_type': 'DownloadError'}
                
                return info

        except Exception as e:
            return {'error': describe_error(e), 'error_type': type(e).__name__}

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None, cancel_event=None):
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
        update; the item is then ``cancelled`` and its partial files removed.
        """
        title = title or url
        partial = PartialFiles()

        def failed(error):
            return ItemResult(url, title, ItemStatus.FAILED, error=error)

        def cancelled():
            removed = partial.cleanup()
            if removed and log_callback:
                log_callback(f"Removed {len(removed)} partial file(s)")
            return ItemResult(url, title, ItemStatus.CANCELLED, error='Cancelled by user')

        def is_cancelled():
            return cancel_event is not None and cancel_event.is_set()

        def check_cancel(d=None):
            if d is not None:
                partial.track(d)
            if is_cancelled():
                raise yt_dlp.utils.DownloadCancelled('Cancelled by user')

        def on_progress(d):
            check_cancel(d)
            if progress_hook:
                progress_hook(d)

        def on_postprocess(d):
            check_cancel()
            if progress_hook:
                progress_hook(d)

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

        try:
            # Phase 1: metadata and format selection, no download.
            with yt_dlp.YoutubeDL(dict(ydl_opts)) as ydl:
                info = ydl.extract_info(url, download=False)
            if info is None:
                return failed('No media information returned')
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
            base = filenames.unique_base(prepared, plan.ext)
            partial.claim(base, new_folders)
            if base != os.path.splitext(prepared)[0] and log_callback:
                log_callback(f"File exists; saving as {os.path.basename(base)}.{plan.ext}")
            ydl_opts['outtmpl'] = filenames.escape_template(base) + '.%(ext)s'
            ydl_opts['postprocessors'] = formats.postprocessors_for(plan, info)
            if trim_requested:
                if not info.get('duration') and log_callback:
                    log_callback("Warning: this source does not report its length; "
                                 "the trim end cannot be checked in advance")
                trim_range = parse_trim_range(
                    options.get('trim_start'), options.get('trim_end'), info.get('duration'))
                # yt-dlp (start, end) çiftleri bekler
                ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [trim_range])
                ydl_opts['force_keyframes_at_cuts'] = True
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
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
            return failed(explain_format_error(describe_error(e), mode, quality))

        problem = verify_output(path)
        if problem:
            return failed(problem)
        return ItemResult(url, title, ItemStatus.COMPLETED, path=path)


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


def explain_format_error(message, mode, quality):
    """Turn yt-dlp's generic 'format is not available' into what it means here."""
    if 'Requested format is not available' not in message:
        return message
    if mode == formats.AUDIO_ONLY:
        return 'This media has no audio track to extract'
    if quality and quality != 'Best':
        return f'No {quality} or lower version of this video is available; try a higher quality'
    return 'No downloadable video format is available for this media'


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
