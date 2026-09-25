import customtkinter as ctk
import threading
import os
import sys
from tkinter import filedialog, messagebox
from logic import DownloadManager, TrimError, parse_trim_range
from utils import resource_path

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class PlaylistSelector(ctk.CTkToplevel):
    def __init__(self, parent, video_list, callback):
        super().__init__(parent)
        self.title("Select Videos")
        self.geometry("600x500")
        
        # Pencere ikonunu burada da ayarla
        try:
            icon_path = resource_path("app.ico")
            self.after(100, lambda: self.iconbitmap(icon_path))
        except: pass

        self.callback = callback
        self.checkboxes = []
        self.vars = []
        self.video_data = video_list

        valid_count = len([v for v in video_list if v is not None])
        self.lbl_title = ctk.CTkLabel(self, text=f"Found {valid_count} playable videos.", font=("Arial", 16, "bold"))
        self.lbl_title.pack(pady=10)

        self.btn_frame = ctk.CTkFrame(self)
        self.btn_frame.pack(fill="x", padx=10)
        self.btn_all = ctk.CTkButton(self.btn_frame, text="Select All", command=self.select_all, width=100)
        self.btn_all.pack(side="left", padx=5)
        self.btn_none = ctk.CTkButton(self.btn_frame, text="Select None", command=self.select_none, width=100, fg_color="gray")
        self.btn_none.pack(side="left", padx=5)

        self.scroll = ctk.CTkScrollableFrame(self, width=550, height=350)
        self.scroll.pack(pady=10, padx=10, fill="both", expand=True)

        self.clean_list_indices = []
        for i, vid in enumerate(video_list):
            if vid is None: continue
            title = vid.get('title', 'Unknown Title')
            if not title: title = f"Video #{i+1}"
            var = ctk.IntVar(value=1)
            chk = ctk.CTkCheckBox(self.scroll, text=title, variable=var)
            chk.pack(anchor="w", pady=5, padx=5)
            self.checkboxes.append(chk)
            self.vars.append(var)
            self.clean_list_indices.append(i)

        self.btn_confirm = ctk.CTkButton(self, text="CONFIRM SELECTION", command=self.confirm_selection, fg_color="#2a9d8f", height=40)
        self.btn_confirm.pack(pady=10, fill="x", padx=20)

    def select_all(self):
        for var in self.vars: var.set(1)
    def select_none(self):
        for var in self.vars: var.set(0)
    def confirm_selection(self):
        selected = []
        for i, var in enumerate(self.vars):
            if var.get() == 1:
                idx = self.clean_list_indices[i]
                v = self.video_data[idx]
                url = v.get('original_url') or v.get('url') or v.get('webpage_url')
                if not url and v.get('id'): url = f"https://www.youtube.com/watch?v={v.get('id')}"
                if url: selected.append({'url': url, 'title': v.get('title', 'Unknown')})
        self.callback(selected)
        self.destroy()

class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Universal Video Downloader Pro")
        self.geometry("900x700")
        self.resizable(False, False)

        # --- İKON YÜKLEME (GÜÇLENDİRİLMİŞ) ---
        self.icon_path = resource_path("app.ico")
        
        # 1. İlk deneme
        self.set_icon()
        
        # 2. CustomTkinter ezerse diye 200ms sonra tekrar dene (Garanti Yöntem)
        self.after(200, self.set_icon)
        # --------------------------------------

        self.manager = DownloadManager()
        self.download_folder = os.path.join(os.path.expanduser("~"), "Downloads", "UniversalVideos")
        self.download_queue = [] 

        self.create_sidebar()
        self.create_main_view()

    def set_icon(self):
        """İkonu güvenli bir şekilde ayarlar"""
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception as e:
                print(f"Icon error: {e}")

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.logo = ctk.CTkLabel(self.sidebar, text="UVD PRO", font=ctk.CTkFont(size=24, weight="bold"))
        self.logo.pack(pady=20)
        self.btn_dest = ctk.CTkButton(self.sidebar, text="Set Folder", command=self.select_folder)
        self.btn_dest.pack(pady=10, padx=20)
        self.lbl_status = ctk.CTkLabel(self.sidebar, text="Ready", text_color="gray")
        self.lbl_status.pack(side="bottom", pady=20)

    def create_main_view(self):
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.pack(side="right", fill="both", expand=True, padx=20, pady=20)
        self.url_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.url_frame.pack(fill="x", pady=(0, 10))
        self.url_entry = ctk.CTkEntry(self.url_frame, placeholder_text="Paste Link...", height=40)
        self.url_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.btn_analyze = ctk.CTkButton(self.url_frame, text="ANALYZE", width=100, height=40, command=self.start_analysis_thread, fg_color="#E9C46A", text_color="black")
        self.btn_analyze.pack(side="right")

        self.opt_frame = ctk.CTkFrame(self.main_frame)
        self.opt_frame.pack(fill="x", pady=10)
        self.cmb_mode = ctk.CTkComboBox(self.opt_frame, values=["Video + Audio", "Audio Only", "Video Only"])
        self.cmb_mode.set("Video + Audio")
        self.cmb_mode.grid(row=0, column=0, padx=10, pady=10)
        self.cmb_format = ctk.CTkComboBox(self.opt_frame, values=["mp4", "mkv", "avi", "mp3", "wav", "aac"])
        self.cmb_format.set("mp4")
        self.cmb_format.grid(row=0, column=1, padx=10, pady=10)
        self.cmb_quality = ctk.CTkComboBox(self.opt_frame, values=["Best", "4K", "1080p", "720p"])
        self.cmb_quality.set("Best")
        self.cmb_quality.grid(row=0, column=2, padx=10, pady=10)
        
        self.chk_trim = ctk.CTkCheckBox(self.opt_frame, text="Trim", command=self.toggle_trim)
        self.chk_trim.grid(row=1, column=0, padx=10, pady=10)
        self.ent_start = ctk.CTkEntry(self.opt_frame, placeholder_text="Start (00:00:10)", state="disabled")
        self.ent_start.grid(row=1, column=1, padx=10, pady=10)
        self.ent_end = ctk.CTkEntry(self.opt_frame, placeholder_text="End (00:00:20)", state="disabled")
        self.ent_end.grid(row=1, column=2, padx=10, pady=10)

        self.btn_download = ctk.CTkButton(self.main_frame, text="START DOWNLOAD", height=50, fg_color="#e63946", hover_color="#d62828", font=("Arial", 16, "bold"), command=self.start_download_queue, state="disabled")
        self.btn_download.pack(fill="x", pady=20)
        self.progress_bar = ctk.CTkProgressBar(self.main_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=10)
        self.lbl_progress = ctk.CTkLabel(self.main_frame, text="0%")
        self.lbl_progress.pack()
        self.console = ctk.CTkTextbox(self.main_frame, height=200)
        self.console.pack(fill="both", expand=True, pady=10)
        self.log("Welcome!")

    def log(self, message):
        self.console.insert("end", f"> {message}\n")
        self.console.see("end")
    def toggle_trim(self):
        state = "normal" if self.chk_trim.get() else "disabled"
        self.ent_start.configure(state=state)
        self.ent_end.configure(state=state)
    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.download_folder = folder
            self.log(f"Destination: {folder}")
    def start_analysis_thread(self):
        url = self.url_entry.get().strip()
        if not url: return
        self.btn_analyze.configure(state="disabled", text="Checking...")
        threading.Thread(target=self.run_analysis, args=(url,)).start()
    def run_analysis(self, url):
        try:
            self.log("Fetching info...")
            info = self.manager.fetch_info(url)
            if info is None:
                self.log("ERROR: Info is None.")
                return
            if 'error' in info:
                self.log(f"FAILED: {info['error']}")
                return
            if 'entries' in info:
                self.log(f"Playlist detected.")
                self.after(0, lambda: PlaylistSelector(self, list(info['entries']), self.set_queue))
            else:
                title = info.get('title', 'Unknown')
                self.log(f"Single Video: {title}")
                self.set_queue([{'url': info.get('original_url', url), 'title': title}])
        except Exception as e:
            self.log(f"Error: {e}")
        finally:
            self.btn_analyze.configure(state="normal", text="ANALYZE")
    def set_queue(self, items):
        self.download_queue = items
        count = len(items)
        if count > 0:
            self.log(f"Queue ready: {count} items.")
            self.btn_download.configure(state="normal", text=f"DOWNLOAD ({count})")
        else:
            self.btn_download.configure(state="disabled", text="START DOWNLOAD")
    def start_download_queue(self):
        if not self.download_queue: return
        if self.chk_trim.get():
            # Kötü trim değerleriyle kuyruğu hiç başlatma
            try:
                if parse_trim_range(self.ent_start.get(), self.ent_end.get()) is None:
                    raise TrimError("Enter a trim start and/or end time")
            except TrimError as e:
                self.log(f"Trim error: {e}")
                messagebox.showerror("Invalid trim range", str(e))
                return
        self.btn_download.configure(state="disabled", text="DOWNLOADING...")
        opts = {
            'save_path': self.download_folder, 'mode': self.cmb_mode.get(),
            'format': self.cmb_format.get(), 'quality': self.cmb_quality.get(),
            'trim_start': self.ent_start.get() if self.chk_trim.get() else None,
            'trim_end': self.ent_end.get() if self.chk_trim.get() else None
        }
        threading.Thread(target=self.run_queue, args=(opts,)).start()
    def run_queue(self, opts):
        total = len(self.download_queue)
        for i, item in enumerate(self.download_queue):
            self.log(f"[{i+1}/{total}] {item['title']}")
            try: self.manager.download_video(item['url'], opts, self.progress_hook, lambda f: None, self.on_error)
            except Exception as e: self.log(f"Failed: {e}")
        self.log("FINISHED.")
        self.btn_download.configure(state="disabled", text="FINISHED")
        self.progress_bar.set(1)
        self.lbl_progress.configure(text="Complete")
        messagebox.showinfo("Done", "Finished!")
    def progress_hook(self, d):
        if d['status'] == 'downloading':
            p = d.get('_percent_str', '0%').replace('%','')
            try:
                self.progress_bar.set(float(p)/100)
                self.lbl_progress.configure(text=f"{d.get('_percent_str')}")
            except: pass
    def on_error(self, msg): self.log(f"Error: {msg}")