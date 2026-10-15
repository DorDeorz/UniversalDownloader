"""Android glue: where files go and how the bundled programs are found.

Android does not let an app run programs from its writable storage. The
APK therefore ships FFmpeg, ffprobe and QuickJS as ``lib<name>.so`` files;
Android unpacks them into the app's native library folder, where running
them is allowed. yt-dlp looks for fixed names (``ffmpeg``, ``ffprobe``,
``qjs``), so :func:`link_tools` puts symlinks with those names in a folder
of their own.

The functions that talk to Android through pyjnius only run on a device;
the rest is plain Python and is unit tested on the desktop.
"""

import os
import re

# Name yt-dlp expects -> file name in the APK's native library folder.
TOOLS = {
    "ffmpeg": "libffmpeg.so",
    "ffprobe": "libffprobe.so",
    "qjs": "libqjs.so",
}
DOWNLOAD_SUBFOLDER = "Orbida"


def on_android():
    return "ANDROID_ARGUMENT" in os.environ or "ANDROID_PRIVATE" in os.environ


def link_tools(native_dir, link_dir):
    """Point ``link_dir/<name>`` at each bundled program that exists.

    The native library folder moves when the app is updated, so the links
    are rebuilt on every start. Returns ``{name: link path}`` for the
    programs found.
    """
    os.makedirs(link_dir, exist_ok=True)
    found = {}
    for name, lib in TOOLS.items():
        target = os.path.join(native_dir, lib)
        link = os.path.join(link_dir, name)
        if not os.path.isfile(target):
            _remove(link)
            continue
        temp = link + ".new"
        _remove(temp)
        os.symlink(target, temp)
        os.replace(temp, link)
        found[name] = link
    return found


def _remove(path):
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


def library_path_env(native_dir, environ):
    """Let the bundled programs find FFmpeg's shared libraries.

    ffmpeg and ffprobe load ``libavcodec.so`` and friends, which sit in the
    native library folder; programs started from the app only search
    there when ``LD_LIBRARY_PATH`` says so.
    """
    # Android's separator, also when the tests run on Windows.
    paths = [p for p in environ.get("LD_LIBRARY_PATH", "").split(":") if p and p != native_dir]
    environ["LD_LIBRARY_PATH"] = ":".join([native_dir, *paths])


def certificate_env(ca_file, environ):
    """Let FFmpeg check HTTPS certificates (it reads from the web when trimming).

    FFmpeg's mbedTLS has no system certificate store on Android; the patch
    in android/native makes it use ``SSL_CERT_FILE``, pointed here at
    certifi's bundle. Python's ssl module honours the same variable.
    """
    if ca_file and os.path.isfile(ca_file):
        environ["SSL_CERT_FILE"] = ca_file


def js_runtime_options(links):
    """yt-dlp options that use the bundled QuickJS for YouTube, if present."""
    if "qjs" not in links:
        return {}
    return {"js_runtimes": {"quickjs": {"path": links["qjs"]}}}


def choose_download_dir(candidates, check):
    """First folder ``check`` accepts; ``check`` returns an error text or None.

    Returns ``(folder, errors)`` where ``errors`` lists why earlier
    candidates were refused, or ``(None, errors)`` when none works.
    """
    errors = []
    for folder in candidates:
        if not folder:
            continue
        error = check(folder)
        if error is None:
            return folder, errors
        errors.append(error)
    return None, errors


_URL = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def find_link(text):
    """The first web link in shared or pasted text, or None.

    Apps share links with extra words around them ("Watch this on TikTok:
    https://vm.tiktok.com/xyz/"), and a sentence may end right after it.
    """
    match = _URL.search(text or "")
    if not match:
        return None
    return match.group(0).rstrip(".,;:!?)]}»”’")


# --- Device-only helpers (pyjnius) -------------------------------------------------


def _activity():
    from jnius import autoclass
    return autoclass("org.kivy.android.PythonActivity").mActivity


def native_library_dir():
    return _activity().getApplicationInfo().nativeLibraryDir


def files_dir():
    return _activity().getFilesDir().getAbsolutePath()


def cache_dir():
    return _activity().getCacheDir().getAbsolutePath()


def public_downloads_dir():
    """``Download/Orbida`` on the shared storage."""
    from jnius import autoclass
    env = autoclass("android.os.Environment")
    base = env.getExternalStoragePublicDirectory(env.DIRECTORY_DOWNLOADS).getAbsolutePath()
    return os.path.join(base, DOWNLOAD_SUBFOLDER)


def app_downloads_dir():
    """The app's own folder on shared storage; always writable, removed on uninstall."""
    folder = _activity().getExternalFilesDir(None)
    return os.path.join(folder.getAbsolutePath(), "Downloads") if folder else None


def sdk_version():
    from jnius import autoclass
    return autoclass("android.os.Build$VERSION").SDK_INT


def request_storage_permission(callback=None):
    """Ask for storage access where Android still needs it (Android 10 and older)."""
    if sdk_version() > 29:
        if callback:
            callback(True)
        return
    from android.permissions import Permission, request_permissions

    def done(permissions, grants):
        if callback:
            callback(all(grants))

    request_permissions([Permission.WRITE_EXTERNAL_STORAGE, Permission.READ_EXTERNAL_STORAGE], done)


def scan_media(path):
    """Tell Android's media index about a new file so galleries and players see it."""
    from jnius import autoclass
    scanner = autoclass("android.media.MediaScannerConnection")
    scanner.scanFile(_activity(), [path], None, None)


def device_language():
    from jnius import autoclass
    return autoclass("java.util.Locale").getDefault().getLanguage()


def clipboard_text():
    """Text on the clipboard, or ''."""
    from kivy.core.clipboard import Clipboard
    return Clipboard.paste() or ""


def forward_native_stderr(callback):
    """Pass each line programs started by the app write to stderr to ``callback``.

    Python's own output goes to Android's log, but the process's stderr
    (which FFmpeg inherits from yt-dlp) goes nowhere, so FFmpeg's reason
    for failing would be lost.
    """
    import threading
    read_fd, write_fd = os.pipe()
    os.dup2(write_fd, 2)
    os.close(write_fd)

    def pump():
        with os.fdopen(read_fd, "r", encoding="utf-8", errors="replace") as lines:
            for line in lines:
                line = line.rstrip()
                if line:
                    callback(line)

    threading.Thread(target=pump, name="native-stderr", daemon=True).start()


def app_log(buffers="main,system,crash", lines=None):
    """This app's own lines from Android's log, oldest first.

    Apps may read only what their own user id logged, which includes the
    Java exception or fatal signal that closed an earlier run of the app.
    """
    import subprocess
    args = ["logcat", "-d", "-v", "threadtime", "-b", buffers]
    if lines:
        args += ["-t", str(lines)]
    try:
        out = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=15)
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout


def night_mode():
    """True when the phone uses its dark theme."""
    config = _activity().getResources().getConfiguration()
    from jnius import autoclass
    Configuration = autoclass("android.content.res.Configuration")
    return (config.uiMode & Configuration.UI_MODE_NIGHT_MASK) == Configuration.UI_MODE_NIGHT_YES


def shared_text(intent=None):
    """Text another app shared with us (Share -> Orbida), or None."""
    from jnius import autoclass
    Intent = autoclass("android.content.Intent")
    intent = intent or _activity().getIntent()
    if intent is None or intent.getAction() != Intent.ACTION_SEND:
        return None
    return intent.getStringExtra(Intent.EXTRA_TEXT)


def bind_new_intent(callback):
    """Call ``callback(text)`` when a link is shared while the app runs.

    Runs on Android's UI thread; ``callback`` must only hand the text over.
    """
    from android import activity

    def on_new_intent(intent):
        text = shared_text(intent)
        if text:
            callback(text)

    activity.bind(on_new_intent=on_new_intent)


def set_keep_screen_on(on):
    """Keep the display from sleeping (only while downloading)."""
    from android.runnable import run_on_ui_thread
    from jnius import autoclass
    flag = autoclass("android.view.WindowManager$LayoutParams").FLAG_KEEP_SCREEN_ON

    @run_on_ui_thread
    def apply():
        window = _activity().getWindow()
        if on:
            window.addFlags(flag)
        else:
            window.clearFlags(flag)

    apply()


class WakeLock:
    """Keeps the CPU running while a download runs, even with the screen off."""

    def __init__(self):
        self._lock = None

    def acquire(self):
        if self._lock is None:
            from jnius import autoclass
            Context = autoclass("android.content.Context")
            PowerManager = autoclass("android.os.PowerManager")
            manager = _activity().getSystemService(Context.POWER_SERVICE)
            self._lock = manager.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Orbida:download")
            self._lock.setReferenceCounted(False)
        # A timeout guards against a lock that is never released.
        self._lock.acquire(6 * 60 * 60 * 1000)

    def release(self):
        if self._lock is not None and self._lock.isHeld():
            self._lock.release()


class DownloadNotice:
    """Background downloads with a progress notification (DownloadService.java).

    While the service runs, Android keeps the app going when the user
    switches to another app. Progress updates are throttled: Android drops
    notification updates that come too fast anyway.
    """

    MIN_INTERVAL = 1.0  # seconds between progress updates

    def __init__(self, clock=None):
        import time
        self._clock = clock or time.monotonic
        self._service = None
        self.running = False
        self._last = (None, None, None)
        self._last_time = 0.0

    def _java(self):
        if self._service is None:
            from jnius import autoclass
            self._service = autoclass("io.github.dordeorz.universaldownloader.DownloadService")
        return self._service

    def start(self, channel, title, text="", percent=-1):
        if self.running:
            return
        service = self._java()
        service.clearDone(_activity())
        service.start(_activity(), channel, title, text, int(percent))
        self.running = True
        self._last = (title, text, int(percent))
        self._last_time = self._clock()

    def update(self, title, text="", percent=-1, force=False):
        """Show new progress; returns whether it was sent to Android."""
        if not self.running:
            return False
        state = (title, text, int(percent))
        now = self._clock()
        if state == self._last or (not force and now - self._last_time < self.MIN_INTERVAL):
            return False
        self._java().update(_activity(), *state)
        self._last, self._last_time = state, now
        return True

    def service_running(self):
        """Whether Android actually started the service (for the self-test)."""
        return bool(self._service is not None and self._service.isRunning())

    def stop(self, done_title=None, done_text=""):
        """End the service; with ``done_title``, leave a "finished" notification."""
        if not self.running:
            return
        service = self._java()
        service.stop(_activity())
        self.running = False
        if done_title:
            service.done(_activity(), done_title, done_text)


def ask_notification_permission():
    """Ask once for permission to show notifications (Android 13+)."""
    from jnius import autoclass
    if autoclass("android.os.Build$VERSION").SDK_INT < 33:
        return
    from android.permissions import Permission, check_permission, request_permissions
    if not check_permission(Permission.POST_NOTIFICATIONS):
        request_permissions([Permission.POST_NOTIFICATIONS])


def open_or_share(path, mime, share=False, on_error=None):
    """Open ``path`` in another app, or offer it to share.

    Android 7+ refuses file:// links between apps, so the file is first
    looked up in the media index, which returns a content:// link other
    apps may read. The lookup answers on a background thread.
    """
    from jnius import PythonJavaClass, autoclass, cast, java_method

    Intent = autoclass("android.content.Intent")
    scanner = autoclass("android.media.MediaScannerConnection")
    activity = _activity()

    class Listener(PythonJavaClass):
        __javainterfaces__ = ["android/media/MediaScannerConnection$OnScanCompletedListener"]
        __javacontext__ = "app"

        @java_method("(Ljava/lang/String;Landroid/net/Uri;)V")
        def onScanCompleted(self, scanned, uri):
            try:
                if uri is None:
                    raise RuntimeError("not in the media index")
                if share:
                    intent = Intent(Intent.ACTION_SEND)
                    intent.setType(mime)
                    intent.putExtra(Intent.EXTRA_STREAM, cast("android.os.Parcelable", uri))
                else:
                    intent = Intent(Intent.ACTION_VIEW)
                    intent.setDataAndType(uri, mime)
                intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                chooser = Intent.createChooser(intent, None) if share else intent
                chooser.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                activity.startActivity(chooser)
            except Exception as e:
                if on_error:
                    on_error(e)

    listener = Listener()
    _listeners.append(listener)  # keep it alive until Android calls back
    del _listeners[:-8]
    scanner.scanFile(activity, [path], [mime], listener)


_listeners = []


def system_bar_insets(window_height):
    """(top, bottom) pixels of the app hidden under the status and navigation bars.

    Apps built for Android 15 draw edge to edge: the window reaches under
    the system bars. When the app's surface is as tall as the whole
    window, keep its content clear of them; when Android already stops the
    surface at the bars, nothing is hidden.
    """
    view = _activity().getWindow().getDecorView()
    insets = view.getRootWindowInsets()
    if insets is None or window_height < view.getHeight() - 1:
        return 0, 0
    return insets.getSystemWindowInsetTop(), insets.getSystemWindowInsetBottom()
