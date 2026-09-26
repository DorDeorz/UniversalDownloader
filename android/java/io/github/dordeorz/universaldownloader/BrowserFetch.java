package io.github.dordeorz.universaldownloader;

import android.app.Activity;
import android.os.Handler;
import android.os.Looper;
import android.webkit.CookieManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import org.json.JSONObject;

import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * A hidden WebView page that makes requests (and mints YouTube's PO tokens)
 * with the phone's own browser engine and cookies. Used by browser_route.py,
 * which holds the page itself, when YouTube asks yt-dlp to "confirm you're
 * not a bot".
 *
 * start() and run() block the calling thread, so Python calls them from its
 * worker threads, never from Android's UI thread.
 */
public class BrowserFetch {
    private static final Handler ui = new Handler(Looper.getMainLooper());
    private static final ConcurrentHashMap<String, String[]> results = new ConcurrentHashMap<String, String[]>();
    private static final ConcurrentHashMap<String, CountDownLatch> waiting = new ConcurrentHashMap<String, CountDownLatch>();
    private static final AtomicInteger ids = new AtomicInteger();
    private static CountDownLatch ready;
    private static volatile boolean loaded;
    private static volatile String error;
    private static WebView web;

    /** Loads ``html`` as if it came from ``baseUrl``, once; returns whether it has loaded. */
    public static boolean start(final Activity activity, final String userAgent, final String baseUrl,
                                final String html, long timeoutMs) throws InterruptedException {
        CountDownLatch latch;
        synchronized (BrowserFetch.class) {
            if (ready == null) {
                ready = new CountDownLatch(1);
                ui.post(new Runnable() {
                    public void run() {
                        create(activity, userAgent, baseUrl, html);
                    }
                });
            }
            latch = ready;
        }
        latch.await(timeoutMs, TimeUnit.MILLISECONDS);
        return loaded;
    }

    /** Why the WebView could not be made, or null. */
    public static String error() {
        return error;
    }

    private static void create(Activity activity, String userAgent, String baseUrl, String html) {
        try {
            web = new WebView(activity);
            WebSettings settings = web.getSettings();
            settings.setJavaScriptEnabled(true);
            settings.setDomStorageEnabled(true);
            if (userAgent != null) {
                settings.setUserAgentString(userAgent);
            }
            CookieManager cookies = CookieManager.getInstance();
            cookies.setAcceptCookie(true);
            cookies.setAcceptThirdPartyCookies(web, true);
            web.addJavascriptInterface(new Bridge(), "UdBridge");
            web.setWebViewClient(new WebViewClient() {
                @Override
                public void onPageFinished(WebView view, String url) {
                    loaded = true;
                    ready.countDown();
                }
            });
            // A browser page the user never sees: one transparent pixel behind the app.
            web.setAlpha(0f);
            activity.addContentView(web, new FrameLayout.LayoutParams(1, 1));
            web.loadDataWithBaseURL(baseUrl, html, "text/html", "utf-8", null);
        } catch (Throwable t) {
            error = t.toString();
            ready.countDown();
        }
    }

    /**
     * Calls the page's ``function(id, ...args)`` and waits for it to answer
     * through UdBridge: {"1" or a status, up to three strings}, or {"0", error}.
     * ``argsJson`` is a JSON array.
     */
    public static String[] run(String function, String argsJson, long timeoutMs) throws InterruptedException {
        if (!loaded || web == null) {
            return new String[]{"0", "the browser page is not loaded"};
        }
        final String id = String.valueOf(ids.incrementAndGet());
        CountDownLatch latch = new CountDownLatch(1);
        waiting.put(id, latch);
        final String call = "window[" + JSONObject.quote(function) + "].apply(null, ["
                + JSONObject.quote(id) + "].concat(" + argsJson + "))";
        ui.post(new Runnable() {
            public void run() {
                web.evaluateJavascript(call, null);
            }
        });
        boolean answered = latch.await(timeoutMs, TimeUnit.MILLISECONDS);
        waiting.remove(id);
        String[] result = results.remove(id);
        if (!answered || result == null) {
            return new String[]{"0", "the browser did not answer in time"};
        }
        return result;
    }

    public static class Bridge {
        @JavascriptInterface
        public void done(String id, String status, String headers, String body, String url) {
            finish(id, new String[]{status, headers, body, url});
        }

        @JavascriptInterface
        public void fail(String id, String message) {
            finish(id, new String[]{"0", message});
        }

        private static void finish(String id, String[] result) {
            CountDownLatch latch = waiting.get(id);
            if (latch != null) {
                results.put(id, result);
                latch.countDown();
            }
        }
    }
}
