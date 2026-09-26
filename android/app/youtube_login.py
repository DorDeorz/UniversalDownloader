"""Signing in to YouTube inside the app, for yt-dlp to use the session.

YouTube answers some networks (often mobile data) with "Sign in to confirm
you're not a bot" whichever player client yt-dlp uses; the fix yt-dlp
documents is to send the cookies of a signed-in session. The app opens
YouTube's sign-in page in an Android WebView, and when the user is done it
writes the WebView's youtube.com cookies to a Netscape cookie file, which
yt-dlp reads through its ``cookiefile`` option.

The file stays in the app's private folder. Signing out deletes it and the
WebView's cookies.
"""

import os
import time

COOKIE_FILE = "youtube-cookies.txt"
LOGIN_URL = "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fm.youtube.com%2F"
# Cookies YouTube sets for a signed-in session; yt-dlp signs its requests with them.
SESSION_COOKIES = ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID")
_YEAR = 365 * 24 * 60 * 60


def parse_cookie_header(header):
    """``name=value`` pairs of a Cookie header (as CookieManager.getCookie returns it)."""
    cookies = {}
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            cookies[name] = value
    return cookies


def signed_in(cookies):
    return any(name in cookies for name in SESSION_COOKIES)


def netscape_file(cookies, now=None):
    """The text of a Netscape cookie file with ``cookies`` for .youtube.com.

    The WebView only reports names and values, so every cookie is written
    for the whole domain, HTTPS only, valid for a year.
    """
    expires = int((time.time() if now is None else now) + _YEAR)
    lines = ["# Netscape HTTP Cookie File", "# Written by UniversalDownloader from its YouTube sign-in", ""]
    for name, value in cookies.items():
        lines.append("\t".join((".youtube.com", "TRUE", "/", "TRUE", str(expires), name, value)))
    return "\n".join(lines) + "\n"


def cookie_path(folder):
    return os.path.join(folder, COOKIE_FILE)


def save(folder, cookie_header):
    """Write the cookie file; returns True when it holds a signed-in session."""
    cookies = parse_cookie_header(cookie_header)
    if not signed_in(cookies):
        return False
    os.makedirs(folder, exist_ok=True)
    path = cookie_path(folder)
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(netscape_file(cookies))
    os.replace(temp, path)
    return True


def saved(folder):
    """The cookie file when a signed-in session is stored, else None."""
    path = cookie_path(folder)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    names = {line.split("\t")[5] for line in text.splitlines() if line.count("\t") >= 6}
    return path if signed_in(names) else None


def forget(folder):
    try:
        os.remove(cookie_path(folder))
    except OSError:
        pass


# --- Device-only (pyjnius) ---------------------------------------------------------


def _browser_user_agent(activity):
    """The WebView's user agent without its WebView markers.

    Google refuses to sign in inside apps that announce an embedded
    WebView; without the markers the page is served as to Chrome.
    """
    from jnius import autoclass
    agent = autoclass("android.webkit.WebSettings").getDefaultUserAgent(activity)
    return agent.replace("; wv)", ")").replace(" Version/4.0", "")


class LoginView:
    """A full-screen WebView over the app, with a Done bar at the top.

    ``on_close(cookie_header)`` runs on Android's UI thread when the user
    taps Done or Back; the caller hands it to Kivy's thread.
    """

    def __init__(self, on_close, done_text="Done"):
        self.on_close = on_close
        self.done_text = done_text
        self._layout = None
        self._keep = []  # Java listeners must outlive the call that made them

    def open(self, url=LOGIN_URL):
        from android.runnable import run_on_ui_thread
        run_on_ui_thread(self._open)(url)

    def close(self):
        from android.runnable import run_on_ui_thread
        run_on_ui_thread(self._close)()

    def _open(self, url):
        # Runs on Android's UI thread, where an error would only reach logcat.
        try:
            self._build(url)
        except Exception:
            import traceback
            print("UDCRASH YouTube sign-in page:\n" + traceback.format_exc(), flush=True)
            self._layout = None
            self.on_close("")

    def _build(self, url):
        from jnius import PythonJavaClass, autoclass, java_method

        activity = autoclass("org.kivy.android.PythonActivity").mActivity
        LinearLayout = autoclass("android.widget.LinearLayout")
        LayoutParams = autoclass("android.view.ViewGroup$LayoutParams")
        Button = autoclass("android.widget.Button")
        WebView = autoclass("android.webkit.WebView")
        WebViewClient = autoclass("android.webkit.WebViewClient")
        CookieManager = autoclass("android.webkit.CookieManager")
        Color = autoclass("android.graphics.Color")
        view = self

        class Done(PythonJavaClass):
            __javainterfaces__ = ["android/view/View$OnClickListener"]
            __javacontext__ = "app"

            @java_method("(Landroid/view/View;)V")
            def onClick(self, _v):
                view._close()

        class Back(PythonJavaClass):
            __javainterfaces__ = ["android/view/View$OnKeyListener"]
            __javacontext__ = "app"

            @java_method("(Landroid/view/View;ILandroid/view/KeyEvent;)Z")
            def onKey(self, _v, code, event):
                if code != 4:  # KEYCODE_BACK
                    return False
                if event.getAction() == 1:  # ACTION_UP
                    if web.canGoBack():
                        web.goBack()
                    else:
                        view._close()
                return True

        cookies = CookieManager.getInstance()
        cookies.setAcceptCookie(True)
        web = WebView(activity)
        cookies.setAcceptThirdPartyCookies(web, True)
        settings = web.getSettings()
        settings.setJavaScriptEnabled(True)
        settings.setDomStorageEnabled(True)
        settings.setUserAgentString(_browser_user_agent(activity))
        web.setWebViewClient(WebViewClient())  # keep pages inside the WebView
        done, back = Done(), Back()
        self._keep = [done, back]
        web.setOnKeyListener(back)

        button = Button(activity)
        button.setText(autoclass("java.lang.String")(self.done_text))  # a CharSequence parameter
        button.setOnClickListener(done)
        layout = LinearLayout(activity)
        layout.setOrientation(LinearLayout.VERTICAL)
        layout.setBackgroundColor(Color.WHITE)
        insets = activity.getWindow().getDecorView().getRootWindowInsets()
        if insets is not None:
            layout.setPadding(0, insets.getSystemWindowInsetTop(), 0, insets.getSystemWindowInsetBottom())
        layout.addView(button, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.WRAP_CONTENT))
        layout.addView(web, autoclass("android.widget.LinearLayout$LayoutParams")(
            LayoutParams.MATCH_PARENT, 0, 1.0))
        activity.addContentView(layout, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        self._layout, self._web = layout, web
        web.loadUrl(url)
        web.requestFocus()

    def _close(self):
        try:
            self._remove()
        except Exception:
            import traceback
            print("UDCRASH YouTube sign-in page:\n" + traceback.format_exc(), flush=True)
            self._layout = None
            self.on_close("")

    def _remove(self):
        if self._layout is None:
            return
        from jnius import autoclass, cast
        manager = autoclass("android.webkit.CookieManager").getInstance()
        manager.flush()
        header = manager.getCookie("https://www.youtube.com") or ""
        layout, web = self._layout, self._web
        self._layout = self._web = None
        cast("android.view.ViewGroup", layout.getParent()).removeView(layout)  # getParent() is a ViewParent
        web.destroy()
        self.on_close(header)


def clear_webview_cookies():
    from android.runnable import run_on_ui_thread
    from jnius import autoclass

    @run_on_ui_thread
    def clear():
        manager = autoclass("android.webkit.CookieManager").getInstance()
        manager.removeAllCookies(None)
        manager.flush()

    clear()
