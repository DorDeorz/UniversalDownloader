import os
import yt_dlp
from utils import get_ffmpeg_path, get_ffprobe_path

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
                ydl_opts['format'] = "bestvideo+bestaudio/best"
            elif quality == '4K':
                ydl_opts['format'] = "bestvideo[height<=2160]+bestaudio/best"
            elif quality == '1080p':
                ydl_opts['format'] = "bestvideo[height<=1080]+bestaudio/best"
            elif quality == '720p':
                ydl_opts['format'] = "bestvideo[height<=720]+bestaudio/best"
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