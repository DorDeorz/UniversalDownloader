import logging
import os
import re
import yt_dlp
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

import formats
from results import ItemResult, ItemStatus, verify_output
from utils import get_ffmpeg_path, get_ffprobe_path

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
    }


def describe_error(exc):
    """Readable message for a yt-dlp or other exception, without yt-dlp's 'ERROR: ' prefix."""
    msg = str(exc).strip()
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
    def __init__(self):
        self.ffmpeg_path = get_ffmpeg_path()
        self.ffprobe_path = get_ffprobe_path()

    def get_platform_name(self, url):
        if "youtube" in url or "youtu.be" in url:
            return "YouTube"
        elif "tiktok" in url:
            return "TikTok"
        elif "instagram" in url:
            return "Instagram"
        elif "twitter" in url or "x.com" in url:
            return "X_Twitter"
        else:
            return "Other"

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

    def download_video(self, url, options, progress_hook=None, log_callback=None, title=None):
        """Download one item and return its :class:`results.ItemResult`.

        Never raises for download problems: yt-dlp, trim and postprocessor
        errors all become a ``failed`` result with a readable message, and a
        result is only ``completed`` when the output file exists and is not
        empty.

        Works in two phases. A metadata pass selects the formats (and gives
        the title and duration); the download pass then runs with options
        that depend on that selection: the trim range, and whether the
        container can be reached by remuxing or needs re-encoding.
        """
        title = title or url

        def failed(error):
            return ItemResult(url, title, ItemStatus.FAILED, error=error)

        mode = options.get('mode', formats.VIDEO_AUDIO)
        quality = options.get('quality', 'Best')
        try:
            plan = formats.build_format_plan(mode, options.get('format', 'mp4'), quality)
            # Validate the trim text before any network access.
            trim_requested = parse_trim_range(options.get('trim_start'), options.get('trim_end')) is not None
        except (formats.FormatError, TrimError) as e:
            return failed(str(e))

        platform = self.get_platform_name(url)
        base_folder = options.get('save_path', os.getcwd())
        output_template = os.path.join(base_folder, platform, '%(title)s.%(ext)s')

        # A failed download must raise, so it becomes a failed result
        # instead of being reported as finished (no 'ignoreerrors').
        ydl_opts = base_ydl_options(log_callback)
        ydl_opts.update({
            'outtmpl': output_template,
            'ffmpeg_location': self.ffmpeg_path,
            'progress_hooks': [progress_hook] if progress_hook else [],
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

            # Phase 2: download with options that depend on the selection.
            ydl_opts['postprocessors'] = formats.postprocessors_for(plan, info)
            if trim_requested:
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
            return failed(explain_format_error(describe_error(e), mode, quality))

        problem = verify_output(path)
        if problem:
            return failed(problem)
        return ItemResult(url, title, ItemStatus.COMPLETED, path=path)


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
