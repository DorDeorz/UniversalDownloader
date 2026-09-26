"""Sending YouTube's page and API requests through the phone's browser engine.

YouTube answers some networks with "Sign in to confirm you're not a bot".
A phone's browser often still gets the videos on such a network, because
YouTube trusts a browser session more than a bare HTTP client. So when
yt-dlp hits that check, the app can route yt-dlp's requests to
www.youtube.com through a hidden WebView: the requests then carry the
browser engine's own network stack, cookies and session, and no account
is needed. Everything else (the video data itself, the player script,
other sites) keeps going through yt-dlp directly.

The module has two halves:

* ``BrowserRequestHandler``, a yt-dlp request handler that only accepts
  requests while the route is enabled and only for ``ROUTED_HOSTS``.
* A *bridge* that performs one request in the browser. On Android it is
  the Java class ``BrowserFetch`` (android/java); tests and the CI probe use
  their own.

``FETCH_SCRIPT`` runs inside the browser page. ``__udFetch`` answers
``[status, headers JSON, body base64, final URL]`` or ``[0, error]``, both
as its promise's value and, on Android, through the ``UdBridge`` interface.
"""

import base64
import io
import json
import threading
import urllib.parse

from yt_dlp.networking.common import RequestHandler, Response, register_preference, register_rh
from yt_dlp.networking.exceptions import HTTPError, TransportError, UnsupportedRequest

HOME_URL = "https://www.youtube.com/"
ROUTED_HOSTS = ("www.youtube.com",)
# Static files are not behind the check and are large (the player script).
DIRECT_PATHS = ("/s/", "/yts/", "/sw.js", "/favicon")
# Headers a page may not set on fetch(); the browser supplies its own.
BROWSER_HEADERS = ("user-agent", "cookie", "origin", "referer", "host", "connection", "content-length",
                   "accept-encoding", "keep-alive", "te", "trailer", "transfer-encoding", "upgrade")
# Hop-by-hop or already undone by fetch(), which hands over a decoded body.
DROPPED_RESPONSE_HEADERS = ("content-encoding", "content-length", "transfer-encoding")

FETCH_SCRIPT = r"""
window.__udFetch = function (id, method, url, headers, body) {
  var answer = function (result) {
    if (window.UdBridge) {
      if (result[0]) UdBridge.done(id, String(result[0]), result[1], result[2], result[3]);
      else UdBridge.fail(id, String(result[1]));
    }
    return result;
  };
  var options = {method: method, headers: headers, credentials: 'include', redirect: 'follow'};
  if (body) {
    var raw = atob(body), bytes = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
    options.body = bytes;
  }
  return fetch(url, options).then(function (response) {
    var head = {};
    response.headers.forEach(function (value, name) { head[name] = value; });
    return response.arrayBuffer().then(function (buffer) {
      var bytes = new Uint8Array(buffer), text = '';
      for (var i = 0; i < bytes.length; i += 0x8000)
        text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return answer([response.status, JSON.stringify(head), btoa(text), response.url]);
    });
  }).catch(function (error) { return answer([0, String(error)]); });
};
"""

_lock = threading.Lock()
_state = {"bridge": None, "enabled": False, "requests": 0}


def enable(bridge):
    """Route YouTube's requests through ``bridge`` from now on."""
    with _lock:
        _state.update(bridge=bridge, enabled=True)


def disable():
    with _lock:
        _state.update(enabled=False)


def enabled():
    return _state["enabled"] and _state["bridge"] is not None


def request_count():
    """Requests answered through the browser so far (for the app log)."""
    return _state["requests"]


def wants(url):
    """Whether a request to ``url`` goes through the browser (when enabled)."""
    parts = urllib.parse.urlsplit(url)
    return (parts.scheme == "https" and (parts.hostname or "") in ROUTED_HOSTS
            and not parts.path.startswith(DIRECT_PATHS))


def browser_headers(headers):
    """The request headers a page may pass on to fetch()."""
    return {name: value for name, value in headers.items()
            if name.lower() not in BROWSER_HEADERS and not name.lower().startswith(("sec-", "proxy-"))}


def response_headers(headers_json):
    headers = json.loads(headers_json or "{}")
    return {name: value for name, value in headers.items() if name.lower() not in DROPPED_RESPONSE_HEADERS}


def desktop_user_agent(agent):
    """A desktop Chrome user agent with the version of the WebView's ``agent``.

    With a phone's user agent www.youtube.com sends the browser on to
    m.youtube.com; yt-dlp's requests go to www.youtube.com, which the page
    can only fetch from its own origin.
    """
    version = "140.0.0.0"
    for part in (agent or "").split():
        if part.startswith("Chrome/"):
            version = part.split("/", 1)[1]
    return ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
            f"Chrome/{version} Safari/537.36")


@register_rh
class BrowserRequestHandler(RequestHandler):
    RH_KEY = "UDBrowser"
    _SUPPORTED_URL_SCHEMES = ("https",)
    # Extensions yt-dlp may attach that the browser handles its own way.
    _TOLERATED_EXTENSIONS = ("timeout", "cookiejar", "legacy_ssl", "keep_header_casing", "impersonate")

    def _validate(self, request):
        if not enabled():
            raise UnsupportedRequest("the browser route is off")
        if not wants(request.url):
            raise UnsupportedRequest("not a routed YouTube address")
        if any(request.proxies.get(key) for key in ("all", "https")):
            raise UnsupportedRequest("a proxy is set")
        extra = set(request.extensions) - set(self._TOLERATED_EXTENSIONS)
        if extra:
            raise UnsupportedRequest(f"Unsupported extensions: {', '.join(sorted(extra))}")

    def _send(self, request):
        bridge = _state["bridge"]
        body = request.data
        if body is not None and not isinstance(body, bytes):
            body = body.read() if hasattr(body, "read") else b"".join(body)
        try:
            result = bridge.fetch(request.method, request.url, browser_headers(self._get_headers(request)),
                                  base64.b64encode(body).decode() if body else None,
                                  self._calculate_timeout(request) + 10)
        except Exception as e:
            raise TransportError(cause=e) from e
        status = int(result[0] or 0) if result else 0
        if not status:
            raise TransportError(f"browser: {result[1] if result and len(result) > 1 else 'no answer'}")
        _state["requests"] += 1
        response = Response(io.BytesIO(base64.b64decode(result[2] or "")), result[3] or request.url,
                            response_headers(result[1]), status=status)
        if not 200 <= status < 300:
            raise HTTPError(response, redirect_loop=False)
        return response


@register_preference(BrowserRequestHandler)
def _prefer_browser(handler, request):
    return 1000  # _validate turns down everything it should not take


# --- Device-only (pyjnius) ---------------------------------------------------------


class AndroidBridge:
    """The Java ``BrowserFetch`` WebView, loaded once on first use.

    ``prepare()`` must run on Kivy's main thread: app classes are only found
    from there. ``fetch`` blocks the calling worker thread.
    """

    START_SECONDS = 25

    def __init__(self):
        self._java = None
        self._origin = None

    def prepare(self):
        from jnius import autoclass
        self._java = autoclass("io.github.dordeorz.universaldownloader.BrowserFetch")
        self._activity = autoclass("org.kivy.android.PythonActivity").mActivity
        agent = autoclass("android.webkit.WebSettings").getDefaultUserAgent(self._activity)
        self._agent = desktop_user_agent(agent)
        return self

    def start(self):
        """Load YouTube's home page in the hidden WebView; returns its origin or None."""
        if self._origin is None:
            origin = self._java.start(self._activity, self._agent, HOME_URL, FETCH_SCRIPT,
                                      self.START_SECONDS * 1000)
            error = self._java.error()
            if error:
                raise RuntimeError(error)
            self._origin = origin
        return self._origin

    def fetch(self, method, url, headers, body_base64, timeout):
        origin = self.start()
        if not origin or not url.startswith(origin + "/"):
            return [0, f"the browser page is on {origin or 'nothing'}"]
        return list(self._java.fetch(method, url, json.dumps(headers), body_base64, int(timeout * 1000)))
