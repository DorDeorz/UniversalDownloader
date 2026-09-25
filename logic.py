import logging
import os
import yt_dlp
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

    def download_video(self, url, options, progress_hook, complete_callback, error_callback, log_callback=None):
        platform = self.get_platform_name(url)
        base_folder = options.get('save_path', os.getcwd())
        output_template = os.path.join(base_folder, platform, '%(title)s.%(ext)s')

        # Temel Ayarlar
        # A failed single download must raise, so it reaches error_callback
        # instead of being reported as finished (no 'ignoreerrors').
        ydl_opts = base_ydl_options(log_callback)
        ydl_opts.update({
            'outtmpl': output_template,
            'ffmpeg_location': self.ffmpeg_path,
            'progress_hooks': [progress_hook],
            # --- KAPAK FOTOĞRAFI AYARI ---
            'writethumbnail': True,  # Önce resmi diske indirir
        })

        mode = options.get('mode', 'Video + Audio')
        fmt = options.get('format', 'mp4')
        quality = options.get('quality', 'Best')

        if mode == 'Audio Only':
            ydl_opts['format'] = 'bestaudio/best'
            # Ses İşleme Zinciri
            ydl_opts['postprocessors'] = [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': fmt,
                    'preferredquality': '192',
                },
                {
                    'key': 'EmbedThumbnail',  # Resmi ses dosyasına gömer
                },
                {
                    'key': 'FFmpegMetadata',  # Şarkı bilgilerini (Artist, Title) gömer
                }
            ]
        else:
            # Video Modları
            if quality == 'Best':
                ydl_opts['format'] = f"bestvideo+bestaudio/best"
            elif quality == '4K':
                ydl_opts['format'] = f"bestvideo[height<=2160]+bestaudio/best"
            elif quality == '1080p':
                ydl_opts['format'] = f"bestvideo[height<=1080]+bestaudio/best"
            elif quality == '720p':
                ydl_opts['format'] = f"bestvideo[height<=720]+bestaudio/best"
            else:
                ydl_opts['format'] = "best"
            
            ydl_opts['merge_output_format'] = fmt
            
            # Video modunda da metadata ve thumbnail gömmek istersen:
            ydl_opts['postprocessors'] = [
                {'key': 'EmbedThumbnail'},
                {'key': 'FFmpegMetadata'}
            ]

        # Trim (Kırpma)
        if options.get('trim_start') or options.get('trim_end'):
            start = options.get('trim_start', '')
            end = options.get('trim_end', 'inf')
            if not start: start = "0"
            section = f"*{start}-{end}"
            ydl_opts['download_ranges'] = yt_dlp.utils.download_range_func(None, [section])
            ydl_opts['force_keyframes_at_cuts'] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise yt_dlp.utils.DownloadError('No media information returned')
                filename = ydl.prepare_filename(info)
                
                # Format dönüşümü sonrası dosya uzantısı değişebilir, doğrusunu bulmaya çalışalım
                if mode == 'Audio Only':
                    base, _ = os.path.splitext(filename)
                    final_filename = f"{base}.{fmt}"
                else:
                    final_filename = filename

        except Exception as e:
            error_callback(describe_error(e))
            return
        complete_callback(final_filename)