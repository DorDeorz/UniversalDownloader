"""Signing in to YouTube, Reddit or Instagram inside the app, for yt-dlp to use the session.

YouTube answers some networks (often mobile data) with "Sign in to confirm
you're not a bot" whichever player client yt-dlp uses; the fix yt-dlp
documents is to send the cookies of a signed-in session. The app opens
YouTube's sign-in page in an Android WebView, and when the user is done it
writes the WebView's youtube.com cookies to a Netscape cookie file, which
yt-dlp reads through its ``cookiefile`` option.

Reddit shows NSFW posts only to signed-in accounts ("Account
authentication is required"); its sign-in works the same way and is just as
optional, as is Instagram's (most of Instagram needs a signed-in account).
Each site's cookies have their own file; when more than one is signed in,
yt-dlp gets one file holding them all (:func:`cookie_file`).

The files stay in the app's private folder. Signing out deletes the site's
file and the WebView's cookies.
"""

import os
import time
from collections import namedtuple

import android_env

Site = namedtuple("Site", "name domain file login_url page session_cookies")

YOUTUBE = Site(
    "YouTube", ".youtube.com", "youtube-cookies.txt",
    "https://accounts.google.com/ServiceLogin?service=youtube&continue=https%3A%2F%2Fm.youtube.com%2F",
    "https://www.youtube.com",
    # Cookies YouTube sets for a signed-in session; yt-dlp signs its requests with them.
    ("SAPISID", "__Secure-3PAPISID", "__Secure-1PAPISID"))
REDDIT = Site("Reddit", ".reddit.com", "reddit-cookies.txt", "https://www.reddit.com/login/",
              "https://www.reddit.com", ("reddit_session",))
INSTAGRAM = Site("Instagram", ".instagram.com", "instagram-cookies.txt", "https://www.instagram.com/accounts/login/",
                 "https://www.instagram.com", ("sessionid",))
SITES = (YOUTUBE, REDDIT, INSTAGRAM)


def site_named(name):
    return next((site for site in SITES if site.name == name), None)

COOKIE_FILE = YOUTUBE.file
LOGIN_URL = YOUTUBE.login_url
SESSION_COOKIES = YOUTUBE.session_cookies
# yt-dlp's cookie file when more than one site is signed in.
COMBINED_FILE = "cookies.txt"
_YEAR = 365 * 24 * 60 * 60


def parse_cookie_header(header):
    """``name=value`` pairs of a Cookie header (as CookieManager.getCookie returns it)."""
    cookies = {}
    for part in (header or "").split(";"):
        name, sep, value = part.strip().partition("=")
        if sep and name:
            cookies[name] = value
    return cookies


def signed_in(cookies, site=YOUTUBE):
    return any(name in cookies for name in site.session_cookies)


def netscape_file(cookies, now=None, site=YOUTUBE):
    """The text of a Netscape cookie file with ``cookies`` for the site's domain.

    The WebView only reports names and values, so every cookie is written
    for the whole domain, HTTPS only, valid for a year.
    """
    expires = int((time.time() if now is None else now) + _YEAR)
    lines = ["# Netscape HTTP Cookie File", f"# Written by Orbida from its {site.name} sign-in", ""]
    for name, value in cookies.items():
        lines.append("\t".join((site.domain, "TRUE", "/", "TRUE", str(expires), name, value)))
    return "\n".join(lines) + "\n"


def cookie_path(folder, site=YOUTUBE):
    return os.path.join(folder, site.file)


def _write(path, text):
    temp = path + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(temp, path)


def save(folder, cookie_header, site=YOUTUBE):
    """Write the site's cookie file; returns True when it holds a signed-in session."""
    cookies = parse_cookie_header(cookie_header)
    if not signed_in(cookies, site):
        return False
    os.makedirs(folder, exist_ok=True)
    _write(cookie_path(folder, site), netscape_file(cookies, site=site))
    return True


def saved(folder, site=YOUTUBE):
    """The site's cookie file when a signed-in session is stored, else None."""
    path = cookie_path(folder, site)
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    names = {line.split("\t")[5] for line in text.splitlines() if line.count("\t") >= 6}
    return path if signed_in(names, site) else None


def cookie_file(folder):
    """The cookie file for yt-dlp: the one signed-in site's, all of them together, or None."""
    paths = [path for path in (saved(folder, site) for site in SITES) if path]
    if len(paths) < 2:
        return paths[0] if paths else None
    lines = ["# Netscape HTTP Cookie File", "# Written by Orbida from its sign-ins", ""]
    for path in paths:
        with open(path, encoding="utf-8") as f:
            lines.extend(line for line in f.read().splitlines() if line.count("\t") >= 6)
    combined = os.path.join(folder, COMBINED_FILE)
    _write(combined, "\n".join(lines) + "\n")
    return combined


def forget(folder, site=YOUTUBE):
    try:
        os.remove(cookie_path(folder, site))
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

    ``dark`` follows the app's theme: a dark bar and page around the site,
    and the site itself in dark colours where Android can darken it.
    """

    def __init__(self, on_close, done_text="Done", site=YOUTUBE, dark=False):
        self.on_close = on_close
        self.done_text = done_text
        self.site = site
        self.dark = dark
        self._layout = None
        self._keep = []  # Java listeners must outlive the call that made them

    def open(self, url=None):
        from android.runnable import run_on_ui_thread
        run_on_ui_thread(self._open)(url or self.site.login_url)

    def close(self):
        from android.runnable import run_on_ui_thread
        run_on_ui_thread(self._close)()

    def _open(self, url):
        # Runs on Android's UI thread, where an error would only reach logcat.
        try:
            self._build(url)
        except Exception:
            import traceback
            print(f"UDCRASH {self.site.name} sign-in page:\n" + traceback.format_exc(), flush=True)
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
        sdk = autoclass("android.os.Build$VERSION").SDK_INT
        if sdk >= 33:
            # Sites without a dark design of their own are darkened (with a dark app theme).
            settings.setAlgorithmicDarkeningAllowed(self.dark)
        elif sdk >= 29:
            settings.setForceDark(2 if self.dark else 0)  # WebSettings.FORCE_DARK_ON / FORCE_DARK_OFF
        background, text = (Color.rgb(18, 18, 18), Color.WHITE) if self.dark else (Color.WHITE, Color.BLACK)
        web.setBackgroundColor(background)
        done, back = Done(), Back()
        self._keep = [done, back]
        web.setOnKeyListener(back)

        button = Button(activity)
        button.setText(autoclass("java.lang.String")(self.done_text))  # a CharSequence parameter
        button.setOnClickListener(done)
        button.setTextColor(text)
        button.setBackgroundColor(Color.rgb(40, 40, 40) if self.dark else Color.rgb(238, 238, 238))
        layout = LinearLayout(activity)
        layout.setOrientation(LinearLayout.VERTICAL)
        layout.setBackgroundColor(background)
        insets = activity.getWindow().getDecorView().getRootWindowInsets()
        if insets is not None:
            # Clear of the status and navigation bars (and, in landscape, the sides).
            left, top, right, bottom = android_env.insets_of(insets, sdk)
            layout.setPadding(left, top, right, bottom)
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
            print(f"UDCRASH {self.site.name} sign-in page:\n" + traceback.format_exc(), flush=True)
            self._layout = None
            self.on_close("")

    def _remove(self):
        if self._layout is None:
            return
        from jnius import autoclass, cast
        manager = autoclass("android.webkit.CookieManager").getInstance()
        manager.flush()
        header = manager.getCookie(self.site.page) or ""
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
