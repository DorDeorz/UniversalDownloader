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
* ``BrowserPTP``, a yt-dlp PO token provider: a browser session's streams
  need proof-of-origin tokens, which the page mints with YouTube's own
  BotGuard, as YouTube's web player does.

Both go through a *bridge* to the page (``PAGE_HTML``). On Android it is
the Java class ``BrowserFetch`` (android/java); tests and the CI probe use
their own. A bridge has ``fetch(method, url, headers, body_base64, timeout)``
answering ``[status, headers JSON, body base64, final URL]`` and
``mint(binding, timeout)`` answering ``[1, token]``; both answer
``[0, error]`` when they fail.
"""

import base64
import io
import json
import threading
import urllib.parse

from yt_dlp.extractor.youtube.pot.provider import (
    PoTokenContext,
    PoTokenProvider,
    PoTokenProviderError,
    PoTokenProviderRejectedRequest,
    PoTokenResponse,
    register_preference as register_pot_preference,
    register_provider,
)
from yt_dlp.extractor.youtube.pot.utils import WEBPO_CLIENTS, get_webpo_content_binding
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
PAGE_PATHS = ("/watch", "/shorts", "/embed")
MINT_SECONDS = 40

# The page runs as https://www.youtube.com/ (loadDataWithBaseURL), so its
# fetch() calls to YouTube are same-origin and carry the browser's cookies.
# It is the app's own page, not YouTube's, so no content policy stops it
# from loading BotGuard.
#
# Every function takes a request id first and answers through
# ``answer(id, [status, a, b, c])`` / ``[0, error]``: to UdBridge on Android,
# and as the returned promise's value for the CI probe.
#
# __udMint makes proof-of-origin (PO) tokens the way YouTube's web player
# does (after LuanRT/BgUtils, MIT): run YouTube's BotGuard challenge, trade
# the result for an integrity token, then mint a token per content binding
# (a video id or visitor id). Streams handed to a browser session need them.
PAGE_SCRIPT = r"""
function answer(id, result) {
  if (window.UdBridge) {
    if (result[0]) UdBridge.done(id, String(result[0]), result[1] || '', result[2] || '', result[3] || '');
    else UdBridge.fail(id, String(result[1]));
  }
  return result;
}
function toBase64(bytes, websafe) {
  var text = '';
  for (var i = 0; i < bytes.length; i += 0x8000)
    text += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
  var out = btoa(text);
  return websafe ? out.replace(/\+/g, '-').replace(/\//g, '_') : out;
}
function fromBase64(text) {
  var raw = atob(text.replace(/-/g, '+').replace(/_/g, '/')), bytes = new Uint8Array(raw.length);
  for (var i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  return bytes;
}

window.__udFetch = function (id, method, url, headers, body, credentials) {
  var options = {method: method, headers: headers, credentials: credentials || 'include', redirect: 'follow'};
  if (body) options.body = fromBase64(body);
  return fetch(url, options).then(function (response) {
    var head = {};
    response.headers.forEach(function (value, name) { head[name] = value; });
    return response.arrayBuffer().then(function (buffer) {
      return answer(id, [response.status, JSON.stringify(head), toBase64(new Uint8Array(buffer)), response.url]);
    });
  }).catch(function (error) { return answer(id, [0, 'fetch: ' + error]); });
};

var GOOG_API_KEY = 'AIzaSyDyT5W0Jh49F30Pqqtyfdf7pDLFKLJoAnw';  // YouTube's public web key
var REQUEST_KEY = 'O43z0dpjhgX20SCx4KAo';
var minter = null, minterExpires = 0;

function looseJson(text) {
  text = text.replace(/\\x([0-9A-Fa-f]{2})/g, function (_, hex) { return String.fromCharCode(parseInt(hex, 16)); });
  text = text.replace(/,\s*([\]}])/g, '$1');
  text = text.replace(/'((?:[^'\\]|\\[\s\S])*)'/g, function (_, inner) { return JSON.stringify(inner.replace(/\\'/g, "'")); });
  text = text.replace(/([{,]\s*)([a-zA-Z0-9_$]+)\s*:/g, '$1"$2":');
  var data = JSON.parse(text);
  for (var key in data) {
    var value = data[key];
    if (typeof value === 'string' && /^\s*[\[{]/.test(value)) { try { data[key] = JSON.parse(value); } catch (e) {} }
  }
  return data;
}
function loadScript(url) {
  return new Promise(function (resolve, reject) {
    var script = document.createElement('script');
    script.src = url;
    script.onload = resolve;
    script.onerror = function () { reject(new Error('could not load ' + url)); };
    document.head.appendChild(script);
  });
}
async function newMinter() {
  var html = await (await fetch('/', {credentials: 'include'})).text();
  var config = html.match(/ytcfg\.set\(({.+?})\);/s);
  if (config) window.yt = {config_: JSON.parse(config[1])};  // BotGuard reads EVENT_ID from it
  var att = html.match(/window\.ytAtN\(\s*({[\s\S]*?})\s*\)/);
  if (!att) throw new Error('no BotGuard challenge on the home page');
  var challenge = looseJson(att[1]).R.bgChallenge;
  await loadScript('https:' + challenge.interpreterUrl.privateDoNotAccessOrElseTrustedResourceUrlWrappedValue);
  var vm = window[challenge.globalName];
  if (!vm || !vm.a) throw new Error('BotGuard did not load');
  var functions = new Promise(function (resolve) {
    vm.a(challenge.program, function (snapshot) { resolve(snapshot); }, true, undefined, function () {},
         [[], []], undefined, false, [function () {}, function () {}, function () {}, function () {}, function () {}]);
  });
  var snapshot = await Promise.race([functions, new Promise(function (_, reject) {
    setTimeout(function () { reject(new Error('BotGuard did not start')); }, 10000); })]);
  var signals = [];
  var botguard = await new Promise(function (resolve) {
    snapshot(resolve, [undefined, undefined, signals, undefined]);
  });
  var response = await fetch('https://jnn-pa.googleapis.com/$rpc/google.internal.waa.v1.Waa/GenerateIT', {
    method: 'POST',
    headers: {'content-type': 'application/json+protobuf', 'x-goog-api-key': GOOG_API_KEY,
              'x-user-agent': 'grpc-web-javascript/0.1'},
    body: JSON.stringify([REQUEST_KEY, botguard])});
  var token = await response.json();
  if (!token[0]) throw new Error('no integrity token: ' + JSON.stringify(token).slice(0, 200));
  if (!signals[0]) throw new Error('BotGuard gave no minter');
  var mint = await signals[0](fromBase64(token[0]));
  if (typeof mint !== 'function') throw new Error('BotGuard minter is not a function');
  return {mint: mint, expires: Date.now() + Math.max(60, (token[1] || 3600) - 300) * 1000};
}

window.__udMint = function (id, binding) {
  if (!minter || minterExpires < Date.now()) {
    minterExpires = Infinity;  // until the new one says how long it lasts
    minter = newMinter().then(function (m) { minterExpires = m.expires; return m; })
                        .catch(function (error) { minter = null; throw error; });
  }
  return minter.then(function (m) {
    return m.mint(new TextEncoder().encode(binding));
  }).then(function (bytes) {
    if (!(bytes instanceof Uint8Array)) throw new Error('BotGuard minted nothing');
    return answer(id, [1, toBase64(bytes, true)]);
  }).catch(function (error) { return answer(id, [0, 'mint: ' + (error && error.message || error)]); });
};
"""
PAGE_HTML = "<!doctype html><html><head><meta charset=utf-8><script>" + PAGE_SCRIPT + "</script></head><body></body></html>"

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


def credentials(url):
    """fetch()'s credentials mode for ``url``.

    The watch page goes without cookies: when it is fetched with the cookies
    of an earlier visit, YouTube refuses its streams even with a PO token.
    The API calls that follow keep the session.
    """
    return "omit" if urllib.parse.urlsplit(url).path.startswith(PAGE_PATHS) else "include"


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
                                  self._calculate_timeout(request) + 10, credentials(request.url))
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


@register_provider
class BrowserPTP(PoTokenProvider):
    PROVIDER_VERSION = "1.0.0"
    BUG_REPORT_LOCATION = "https://github.com/DorDeorz/UniversalDownloader/issues"
    _SUPPORTED_CLIENTS = WEBPO_CLIENTS
    _SUPPORTED_CONTEXTS = (PoTokenContext.GVS, PoTokenContext.PLAYER, PoTokenContext.SUBS)

    def is_available(self):
        return enabled()

    def _real_request_pot(self, request):
        binding, _ = get_webpo_content_binding(request)
        if not binding:
            raise PoTokenProviderRejectedRequest("nothing to bind the token to")
        try:
            result = _state["bridge"].mint(binding, MINT_SECONDS)
        except Exception as e:
            raise PoTokenProviderError(f"browser: {e}") from e
        if not result or not result[0] or result[0] == "0":
            raise PoTokenProviderError(f"browser: {result[1] if result and len(result) > 1 else 'no answer'}")
        # expires_at=0: not cached. A token from an earlier browser session
        # gets later sessions' streams refused.
        return PoTokenResponse(po_token=result[1], expires_at=0)


@register_pot_preference(BrowserPTP)
def _prefer_browser_tokens(provider, request):
    return 1000


# --- Device-only (pyjnius) ---------------------------------------------------------


class AndroidBridge:
    """The Java ``BrowserFetch`` WebView, loaded on first use.

    ``prepare()`` must run on Kivy's main thread: app classes are only found
    from there. ``fetch`` and ``mint`` block the calling worker thread.
    """

    START_SECONDS = 20

    def __init__(self):
        self._java = None

    def prepare(self):
        from jnius import autoclass
        self._java = autoclass("io.github.dordeorz.universaldownloader.BrowserFetch")
        self._activity = autoclass("org.kivy.android.PythonActivity").mActivity
        agent = autoclass("android.webkit.WebSettings").getDefaultUserAgent(self._activity)
        self._agent = desktop_user_agent(agent)
        return self

    def _start(self):
        # Returns at once while the page is loaded; loads it again if Android ended it.
        if not self._java.start(self._activity, self._agent, HOME_URL, PAGE_HTML, self.START_SECONDS * 1000):
            raise RuntimeError(self._java.error() or "the browser page did not load")

    def _run(self, function, args, timeout):
        self._start()
        return list(self._java.run(function, json.dumps(args), int(timeout * 1000)))

    def fetch(self, method, url, headers, body_base64, timeout, credentials="include"):
        return self._run("__udFetch", [method, url, headers, body_base64, credentials], timeout)

    def mint(self, binding, timeout):
        return self._run("__udMint", [binding], timeout)
