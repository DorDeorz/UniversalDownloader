import logging

import customtkinter as ctk
import threading
import os
from tkinter import filedialog, messagebox
import events
import formats
from logic import DownloadManager, TrimError, parse_trim_range
from results import ItemResult, ItemStatus, JobSummary
from utils import resource_path

_log = logging.getLogger(__name__)

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
        self.analyzed_url = None
        # Only one job (analysis or download) runs at a time; see _start_job.
        self._job_thread = None
        self._job_kind = None
        self._cancel_event = threading.Event()
        self._closing = False
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Worker threads never touch widgets; they post events that are
        # dispatched here on the main thread (see events.py).
        self.events = events.EventQueue()
        self.events.register(events.LOG, self._append_log)
        self.events.register(events.PROGRESS, self._show_progress)
        self.events.register(events.ANALYSIS_DONE, self._on_analysis_done)
        self.events.register(events.ANALYSIS_FAILED, self._on_analysis_failed)
        self.events.register(events.ITEM_DONE, self._on_item_done)
        self.events.register(events.JOB_DONE, self._on_job_done)
        self.last_summary = None
        self._poll_id = None

        self.create_sidebar()
        self.create_main_view()
        self._poll_events()

    POLL_INTERVAL_MS = 50

    def _poll_events(self):
        """Drain the event queue on the main thread, then reschedule."""
        try:
            self.events.dispatch_pending()
        finally:
            self._poll_id = self.after(self.POLL_INTERVAL_MS, self._poll_events)

    def destroy(self):
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        super().destroy()

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
        self.url_entry.bind("<KeyRelease>", self._on_url_changed)
        self.btn_analyze = ctk.CTkButton(self.url_frame, text="ANALYZE", width=100, height=40, command=self.start_analysis_thread, fg_color="#E9C46A", text_color="black")
        self.btn_analyze.pack(side="right")

        self.opt_frame = ctk.CTkFrame(self.main_frame)
        self.opt_frame.pack(fill="x", pady=10)
        # Read-only boxes: only the choices each mode supports can be picked.
        self.cmb_mode = ctk.CTkComboBox(self.opt_frame, values=list(formats.MODES), state="readonly",
                                        command=self._on_mode_changed)
        self.cmb_mode.grid(row=0, column=0, padx=10, pady=10)
        self.cmb_format = ctk.CTkComboBox(self.opt_frame, values=[], state="readonly")
        self.cmb_format.grid(row=0, column=1, padx=10, pady=10)
        self.cmb_quality = ctk.CTkComboBox(self.opt_frame, values=[], state="readonly")
        self.cmb_quality.grid(row=0, column=2, padx=10, pady=10)
        self.cmb_mode.set(formats.VIDEO_AUDIO)
        self._on_mode_changed(formats.VIDEO_AUDIO)
        
        self.chk_trim = ctk.CTkCheckBox(self.opt_frame, text="Trim", command=self.toggle_trim)
        self.chk_trim.grid(row=1, column=0, padx=10, pady=10)
        self.ent_start = ctk.CTkEntry(self.opt_frame, placeholder_text="Start (00:00:10)", state="disabled")
        self.ent_start.grid(row=1, column=1, padx=10, pady=10)
        self.ent_end = ctk.CTkEntry(self.opt_frame, placeholder_text="End (00:00:20)", state="disabled")
        self.ent_end.grid(row=1, column=2, padx=10, pady=10)

        self.btn_download = ctk.CTkButton(self.main_frame, text="START DOWNLOAD", height=50, fg_color="#e63946", hover_color="#d62828", font=("Arial", 16, "bold"), command=self.start_download_queue, state="disabled")
        self.btn_download.pack(fill="x", pady=(20, 5))
        self.action_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.action_frame.pack(fill="x")
        self.btn_cancel = ctk.CTkButton(self.action_frame, text="CANCEL", command=self.cancel_job, state="disabled",
                                        fg_color="gray30", hover_color="gray25")
        self.btn_cancel.pack(side="left", expand=True, fill="x", padx=(0, 5))
        self.btn_retry = ctk.CTkButton(self.action_frame, text="RETRY FAILED", command=self.retry_failed,
                                       state="disabled", fg_color="gray30", hover_color="gray25")
        self.btn_retry.pack(side="left", expand=True, fill="x", padx=(5, 0))
        self.progress_bar = ctk.CTkProgressBar(self.main_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(fill="x", pady=10)
        self.lbl_progress = ctk.CTkLabel(self.main_frame, text="0%")
        self.lbl_progress.pack()
        self.console = ctk.CTkTextbox(self.main_frame, height=200)
        self.console.pack(fill="both", expand=True, pady=10)
        self.log("Welcome!")

    def log(self, message):
        """Queue a console line; safe to call from any thread."""
        self.events.post(events.LOG, message=message)
    def _append_log(self, message):
        self.console.insert("end", f"> {message}\n")
        self.console.see("end")
    def _show_progress(self, fraction, text):
        self.progress_bar.set(fraction)
        self.lbl_progress.configure(text=text)
    def _on_mode_changed(self, mode):
        """Offer only the formats and qualities that are valid for ``mode``."""
        choices = formats.formats_for_mode(mode)
        self.cmb_format.configure(values=choices)
        if self.cmb_format.get() not in choices:
            self.cmb_format.set(choices[0])
        qualities = formats.qualities_for_mode(mode)
        self.cmb_quality.configure(values=qualities)
        if self.cmb_quality.get() not in qualities:
            self.cmb_quality.set(qualities[0])
    def toggle_trim(self):
        state = "normal" if self.chk_trim.get() else "disabled"
        self.ent_start.configure(state=state)
        self.ent_end.configure(state=state)
    def select_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            self.download_folder = folder
            self.log(f"Destination: {folder}")
    def is_busy(self):
        return self._job_kind is not None

    def _start_job(self, kind, target, *args):
        """Start a worker thread unless another job is running.

        Returns False (and starts nothing) when a job is already active, so a
        second click cannot run two workers against the same state.
        """
        if self.is_busy():
            self._append_log(f"Busy: wait for the current {self._job_kind} to finish.")
            return False
        self._job_kind = kind
        self._cancel_event = threading.Event()
        self._set_controls_busy(True)
        self._job_thread = threading.Thread(target=target, args=args, name=f"uvd-{kind}", daemon=True)
        self._job_thread.start()
        return True

    def _end_job(self):
        self._job_kind = None
        self._job_thread = None
        self._set_controls_busy(False)

    def _set_controls_busy(self, busy):
        state = "disabled" if busy else "normal"
        for widget in (self.url_entry, self.btn_analyze, self.btn_dest, self.chk_trim):
            widget.configure(state=state)
        for combo in (self.cmb_mode, self.cmb_format, self.cmb_quality):
            combo.configure(state="disabled" if busy else "readonly")
        trim_state = "normal" if (not busy and self.chk_trim.get()) else "disabled"
        self.ent_start.configure(state=trim_state)
        self.ent_end.configure(state=trim_state)
        # Only downloads can be cancelled; analysis is a single request
        # bounded by the network timeout.
        self.btn_cancel.configure(state="normal" if busy and self._job_kind == "download" else "disabled",
                                  text="CANCEL")
        if busy:
            self.btn_download.configure(state="disabled")
            self.btn_retry.configure(state="disabled")
        else:
            self._refresh_download_button()
            self._refresh_retry_button()

    def _refresh_download_button(self):
        count = len(self.download_queue)
        if count:
            self.btn_download.configure(state="normal", text=f"DOWNLOAD ({count})")
        else:
            self.btn_download.configure(state="disabled", text="START DOWNLOAD")

    def _failed_items(self):
        if self.last_summary is None:
            return []
        return [{'url': r.url, 'title': r.title} for r in self.last_summary.with_status(ItemStatus.FAILED)]

    def _refresh_retry_button(self):
        count = len(self._failed_items())
        if count:
            self.btn_retry.configure(state="normal", text=f"RETRY FAILED ({count})")
        else:
            self.btn_retry.configure(state="disabled", text="RETRY FAILED")

    def cancel_job(self):
        """Ask the running download to stop; results arrive via job_done."""
        if self._job_kind != "download" or self._cancel_event.is_set():
            return
        self._cancel_event.set()
        self.btn_cancel.configure(state="disabled", text="CANCELLING...")
        self._append_log("Cancelling...")

    def retry_failed(self):
        items = self._failed_items()
        if not items or self.is_busy():
            return
        self._append_log(f"Retrying {len(items)} failed item(s).")
        self.download_queue = items
        self.start_download_queue()

    CLOSE_TIMEOUT_MS = 15000

    def on_close(self):
        """Window close: confirm, cancel a running download, wait, then exit."""
        if self._closing:
            return
        if self._job_kind == "download":
            if not messagebox.askyesno("Download in progress",
                                       "A download is still running. Cancel it and quit?", parent=self):
                return
            self._closing = True
            self.cancel_job()
            self._wait_then_destroy(self.CLOSE_TIMEOUT_MS)
            return
        # An analysis is one bounded request on a daemon thread; nothing to
        # clean up, so the window can close right away.
        self._closing = True
        self.destroy()

    def _wait_then_destroy(self, remaining_ms):
        thread = self._job_thread
        if thread is None or not thread.is_alive() or remaining_ms <= 0:
            if thread is not None and thread.is_alive():
                _log.warning("Worker did not stop within %d ms; closing anyway", self.CLOSE_TIMEOUT_MS)
            self.destroy()
            return
        self.after(100, self._wait_then_destroy, remaining_ms - 100)

    def _on_url_changed(self, _event=None):
        """Drop the analysed queue as soon as the URL no longer matches it."""
        if self.is_busy() or self.analyzed_url is None:
            return
        if self.url_entry.get().strip() != self.analyzed_url:
            self.analyzed_url = None
            self.set_queue([])

    def start_analysis_thread(self):
        url = self.url_entry.get().strip()
        if not url or self.is_busy(): return
        # A new analysis invalidates the previous queue and progress.
        self.analyzed_url = None
        self.set_queue([])
        self._show_progress(0, "0%")
        if self._start_job("analysis", self.run_analysis, url):
            self.btn_analyze.configure(text="Checking...")
    def run_analysis(self, url):
        """Worker thread: fetch info and post the result; no widget access."""
        try:
            self.log("Fetching info...")
            info = self.manager.fetch_info(url)
            if info is None:
                self.events.post(events.ANALYSIS_FAILED, message="ERROR: Info is None.")
            elif 'error' in info:
                self.events.post(events.ANALYSIS_FAILED, message=f"FAILED: {info['error']}")
            else:
                self.events.post(events.ANALYSIS_DONE, info=info, url=url)
        except Exception as e:
            self.events.post(events.ANALYSIS_FAILED, message=f"Error: {e}")
    def _on_analysis_failed(self, message):
        self._append_log(message)
        self.btn_analyze.configure(text="ANALYZE")
        self._end_job()
    def _on_analysis_done(self, info, url):
        self.btn_analyze.configure(text="ANALYZE")
        self._end_job()
        self.analyzed_url = url
        if 'entries' in info:
            self._append_log("Playlist detected.")
            PlaylistSelector(self, list(info['entries']), self.set_queue)
        else:
            title = info.get('title', 'Unknown')
            self._append_log(f"Single Video: {title}")
            self.set_queue([{'url': info.get('original_url', url), 'title': title}])
    def set_queue(self, items):
        self.download_queue = list(items)
        if self.download_queue:
            self.log(f"Queue ready: {len(self.download_queue)} items.")
        if not self.is_busy():
            self._refresh_download_button()
    def start_download_queue(self):
        if not self.download_queue or self.is_busy(): return
        if self.chk_trim.get():
            # Kötü trim değerleriyle kuyruğu hiç başlatma
            try:
                if parse_trim_range(self.ent_start.get(), self.ent_end.get()) is None:
                    raise TrimError("Enter a trim start and/or end time")
            except TrimError as e:
                self.log(f"Trim error: {e}")
                messagebox.showerror("Invalid trim range", str(e))
                return
        self._show_progress(0, "0%")
        items = list(self.download_queue)
        opts = {
            'save_path': self.download_folder, 'mode': self.cmb_mode.get(),
            'format': self.cmb_format.get(), 'quality': self.cmb_quality.get(),
            'trim_start': self.ent_start.get() if self.chk_trim.get() else None,
            'trim_end': self.ent_end.get() if self.chk_trim.get() else None
        }
        if self._start_job("download", self._run_queue_with_cancel, items, opts):
            self.btn_download.configure(text="DOWNLOADING...")
    def run_queue(self, items, opts, cancel_event=None):
        """Worker thread: download each item and post events; no widget access."""
        summary = JobSummary()
        total = len(items)
        try:
            for i, item in enumerate(items):
                if cancel_event is not None and cancel_event.is_set():
                    result = ItemResult(item['url'], item['title'], ItemStatus.CANCELLED, error='Cancelled by user')
                    summary.add(result)
                    self.events.post(events.ITEM_DONE, result=result)
                    continue
                self.log(f"[{i+1}/{total}] {item['title']}")
                try:
                    result = self.manager.download_video(
                        item['url'], opts, self.progress_hook, log_callback=self.log, title=item['title'],
                        cancel_event=cancel_event)
                except Exception as e:
                    result = ItemResult(item['url'], item['title'], ItemStatus.FAILED, error=str(e) or type(e).__name__)
                summary.add(result)
                self.events.post(events.ITEM_DONE, result=result)
        finally:
            self.events.post(events.JOB_DONE, summary=summary)
    def _run_queue_with_cancel(self, items, opts):
        # Bound at start so a later job's event cannot leak into this one.
        self.run_queue(items, opts, self._cancel_event)
    def _on_item_done(self, result):
        self._append_log(result.describe())
    def _on_job_done(self, summary):
        self._append_log(f"Result: {summary.headline()}")
        self.last_summary = summary
        self._end_job()
        if self._closing:
            return
        if summary.all_ok:
            self._show_progress(1, "Complete")
            messagebox.showinfo(summary.title(), summary.report())
        else:
            self._show_progress(self.progress_bar.get(), summary.headline())
            messagebox.showwarning(summary.title(), summary.report())
    def progress_hook(self, d):
        """yt-dlp progress hook; runs on the worker thread."""
        progress = events.progress_from_hook(d)
        if progress is not None:
            fraction, text = progress
            self.events.post(events.PROGRESS, fraction=fraction, text=text)
    def on_error(self, msg): self.log(f"Error: {msg}")
