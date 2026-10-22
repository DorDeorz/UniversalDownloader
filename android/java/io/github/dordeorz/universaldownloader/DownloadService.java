package io.github.dordeorz.universaldownloader;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

/**
 * Keeps downloads running while the app is in the background and shows
 * their progress in a notification.
 *
 * The download itself stays in the app's Python thread: a running
 * foreground service only tells Android that the process is doing work the
 * user asked for, so it is not stopped when the user switches apps.
 *
 * Python calls the static methods from any thread:
 * start() when a download begins, update() as it goes, stop() when it ends
 * and done() to leave a "finished" notification behind.
 *
 * The progress notification has Pause (Resume) and Cancel buttons, the
 * finished one an Open button. A button sends its action to this service,
 * which keeps it until Python picks it up with takeAction().
 * The manifest entry (foregroundServiceType="dataSync") is added by
 * android/p4a_hook.py.
 */
public class DownloadService extends Service {
    private static final String CHANNEL = "downloads";
    private static final int PROGRESS_ID = 1;
    private static final int DONE_ID = 2;

    private static volatile String title = "";
    private static volatile String text = "";
    private static volatile int percent = -1;
    private static volatile String channelName = "Downloads";
    private static volatile boolean running;
    private static volatile boolean paused;
    private static volatile String action = "";
    private static volatile String pauseLabel = "Pause";
    private static volatile String resumeLabel = "Resume";
    private static volatile String cancelLabel = "Cancel";
    private static volatile String openLabel = "Open";

    static final String ACTION_PAUSE = "io.github.dordeorz.orbida.PAUSE";
    static final String ACTION_RESUME = "io.github.dordeorz.orbida.RESUME";
    static final String ACTION_CANCEL = "io.github.dordeorz.orbida.CANCEL";

    /** The buttons' texts in the app's language. */
    public static void setLabels(String pause, String resume, String cancel, String open) {
        pauseLabel = pause;
        resumeLabel = resume;
        cancelLabel = cancel;
        openLabel = open;
    }

    /** "pause", "resume" or "cancel" if a button was pressed since the last call, else "". */
    public static String takeAction() {
        String taken = action;
        action = "";
        return taken;
    }

    public static void start(Context context, String channel, String newTitle, String newText, int newPercent) {
        channelName = channel;
        title = newTitle;
        text = newText;
        percent = newPercent;
        paused = false;
        action = "";
        Context app = context.getApplicationContext();
        Intent intent = new Intent(app, DownloadService.class);
        if (Build.VERSION.SDK_INT >= 26) {
            app.startForegroundService(intent);
        } else {
            app.startService(intent);
        }
    }

    public static void update(Context context, String newTitle, String newText, int newPercent,
                              boolean newPaused) {
        title = newTitle;
        text = newText;
        percent = newPercent;
        paused = newPaused;
        if (running) {
            Context app = context.getApplicationContext();
            manager(app).notify(PROGRESS_ID, build(app, true));
        }
    }

    public static void stop(Context context) {
        Context app = context.getApplicationContext();
        app.stopService(new Intent(app, DownloadService.class));
    }

    /** A dismissable notification saying the downloads have finished. */
    public static void done(Context context, String newTitle, String newText) {
        Context app = context.getApplicationContext();
        title = newTitle;
        text = newText;
        percent = -1;
        createChannel(app);
        manager(app).notify(DONE_ID, build(app, false));
    }

    public static void clearDone(Context context) {
        manager(context.getApplicationContext()).cancel(DONE_ID);
    }

    public static boolean isRunning() {
        return running;
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String pressed = intent != null ? intent.getAction() : null;
        if (pressed != null) {
            // A notification button: Python picks the action up (takeAction).
            if (ACTION_PAUSE.equals(pressed)) {
                action = "pause";
            } else if (ACTION_RESUME.equals(pressed)) {
                action = "resume";
            } else if (ACTION_CANCEL.equals(pressed)) {
                action = "cancel";
            }
            if (!running) {
                stopSelf(startId);  // the download had already ended
            }
            return START_NOT_STICKY;
        }
        createChannel(this);
        Notification notification = build(this, true);
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(PROGRESS_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(PROGRESS_ID, notification);
        }
        running = true;
        // If Android ends the process, the download is gone too: do not restart.
        return START_NOT_STICKY;
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onDestroy() {
        running = false;
        stopForeground(true);
        super.onDestroy();
    }

    /** Android 15 ends long data transfers after their daily time limit. */
    @Override
    public void onTimeout(int startId, int fgsType) {
        stopSelf();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    private static NotificationManager manager(Context context) {
        return (NotificationManager) context.getSystemService(Context.NOTIFICATION_SERVICE);
    }

    private static void createChannel(Context context) {
        if (Build.VERSION.SDK_INT < 26) {
            return;
        }
        // Low importance: shown in the shade without a sound for every update.
        NotificationChannel channel =
                new NotificationChannel(CHANNEL, channelName, NotificationManager.IMPORTANCE_LOW);
        channel.setShowBadge(false);
        manager(context).createNotificationChannel(channel);
    }

    @SuppressWarnings("deprecation")
    private static Notification build(Context context, boolean progress) {
        Notification.Builder builder = Build.VERSION.SDK_INT >= 26
                ? new Notification.Builder(context, CHANNEL)
                : new Notification.Builder(context);
        builder.setSmallIcon(progress ? android.R.drawable.stat_sys_download
                                      : android.R.drawable.stat_sys_download_done)
                .setContentTitle(title)
                .setContentText(text)
                .setOnlyAlertOnce(true)
                .setShowWhen(!progress)
                .setOngoing(progress)
                .setAutoCancel(!progress);
        if (progress) {
            builder.setProgress(100, Math.max(percent, 0), percent < 0);
        }
        Intent open = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        PendingIntent openApp = null;
        if (open != null) {
            open.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            openApp = PendingIntent.getActivity(
                    context, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            builder.setContentIntent(openApp);
        }
        if (progress) {
            builder.addAction(button(context, paused ? android.R.drawable.ic_media_play
                                                     : android.R.drawable.ic_media_pause,
                                     paused ? resumeLabel : pauseLabel, paused ? ACTION_RESUME : ACTION_PAUSE, 1));
            builder.addAction(button(context, android.R.drawable.ic_menu_close_clear_cancel,
                                     cancelLabel, ACTION_CANCEL, 2));
        } else if (openApp != null) {
            builder.addAction(new Notification.Action.Builder(
                    android.graphics.drawable.Icon.createWithResource(context, android.R.drawable.ic_menu_view),
                    openLabel, openApp).build());
        }
        return builder.build();
    }

    private static Notification.Action button(Context context, int icon, String label, String pressed, int code) {
        Intent intent = new Intent(context, DownloadService.class).setAction(pressed);
        PendingIntent sent = PendingIntent.getService(
                context, code, intent, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        return new Notification.Action.Builder(
                android.graphics.drawable.Icon.createWithResource(context, icon), label, sent).build();
    }
}
