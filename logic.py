import os
import re
import yt_dlp
from utils import get_ffmpeg_path, get_ffprobe_path

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

    def fetch_info(self, url):
        """ 
        Playlist veya video bilgisini çeker.
        Hata olursa None döndürmez, 'error' anahtarı olan bir sözlük döndürür.
        """
        ydl_opts = {
            'extract_flat': True,
            'quiet': True,
            'ignoreerrors': True,
            'no_warnings': True,
        }
        
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if info is None:
                    return {'error': 'Content is private or unavailable'}
                
                return info

        except Exception as e:
            return {'error': str(e)}

    def download_video(self, url, options, progress_hook, complete_callback, error_callback):
        platform = self.get_platform_name(url)
        base_folder = options.get('save_path', os.getcwd())
        output_template = os.path.join(base_folder, platform, '%(title)s.%(ext)s')

        # Temel Ayarlar
        ydl_opts = {
            'outtmpl': output_template,
            'ffmpeg_location': self.ffmpeg_path,
            'progress_hooks': [progress_hook],
            'nocheckcertificate': True,
            'ignoreerrors': True,
            'quiet': True,
            'no_warnings': True,
            # --- KAPAK FOTOĞRAFI AYARI ---
            'writethumbnail': True,  # Önce resmi diske indirir
        }

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

        # Trim (Kırpma): metni önceden doğrula, kötü değerle indirmeye başlama
        try:
            trim_requested = parse_trim_range(options.get('trim_start'), options.get('trim_end')) is not None
        except TrimError as e:
            error_callback(str(e))
            return
        if trim_requested:
            ydl_opts['force_keyframes_at_cuts'] = True

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                if trim_requested:
                    # Süreyi öğrenmek için önce bilgiyi çek, aralığı videonun süresine göre doğrula
                    info = ydl.extract_info(url, download=False)
                    if info is None:
                        error_callback("Content is private or unavailable")
                        return
                    try:
                        trim_range = parse_trim_range(
                            options.get('trim_start'), options.get('trim_end'), info.get('duration'))
                    except TrimError as e:
                        error_callback(str(e))
                        return
                    # yt-dlp (start, end) çiftleri bekler
                    ydl.params['download_ranges'] = yt_dlp.utils.download_range_func(None, [trim_range])
                    info = ydl.process_ie_result(info, download=True)
                else:
                    info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Format dönüşümü sonrası dosya uzantısı değişebilir, doğrusunu bulmaya çalışalım
                if mode == 'Audio Only':
                    base, _ = os.path.splitext(filename)
                    final_filename = f"{base}.{fmt}"
                else:
                    final_filename = filename

                complete_callback(final_filename)
        except Exception as e:
            error_callback(str(e))