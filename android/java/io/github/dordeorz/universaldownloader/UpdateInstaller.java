package io.github.dordeorz.universaldownloader;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInstaller;
import android.os.Build;

import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.io.OutputStream;

/**
 * Installs a downloaded APK of the app over itself with Android's
 * PackageInstaller. Android shows its own "update this app?" screen (and,
 * the first time, asks the user to allow installs from this app), checks
 * that the APK is signed with the same key, replaces the app and ends the
 * running one.
 *
 * install() returns at once; status() tells Python how it went:
 * "" (nothing yet), "working", "confirm" (Android's screen is showing),
 * "success", or "failed: ..." with Android's reason.
 */
public class UpdateInstaller {
    private static final String ACTION = "io.github.dordeorz.orbida.UPDATE_STATUS";
    private static volatile String status = "";
    private static BroadcastReceiver receiver;

    public static String status() {
        return status;
    }

    public static void install(final Activity activity, final String apkPath) {
        status = "working";
        new Thread(new Runnable() {
            public void run() {
                try {
                    commit(activity, new File(apkPath));
                } catch (Throwable t) {
                    status = "failed: " + t;
                }
            }
        }).start();
    }

    private static void commit(Activity activity, File apk) throws Exception {
        Context context = activity.getApplicationContext();
        listen(context);
        PackageInstaller installer = context.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams params =
                new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        params.setAppPackageName(context.getPackageName());
        params.setSize(apk.length());
        int id = installer.createSession(params);
        PackageInstaller.Session session = installer.openSession(id);
        try {
            InputStream in = new FileInputStream(apk);
            OutputStream out = session.openWrite("update.apk", 0, apk.length());
            try {
                byte[] buffer = new byte[256 * 1024];
                int n;
                while ((n = in.read(buffer)) > 0) {
                    out.write(buffer, 0, n);
                }
                session.fsync(out);
            } finally {
                in.close();
                out.close();
            }
            Intent intent = new Intent(ACTION).setPackage(context.getPackageName());
            int flags = PendingIntent.FLAG_UPDATE_CURRENT;
            if (Build.VERSION.SDK_INT >= 31) {
                flags |= PendingIntent.FLAG_MUTABLE;  // Android fills in the result
            }
            PendingIntent result = PendingIntent.getBroadcast(context, id, intent, flags);
            session.commit(result.getIntentSender());
        } catch (Exception e) {
            session.abandon();
            throw e;
        } finally {
            session.close();
        }
    }

    private static synchronized void listen(Context context) {
        if (receiver != null) {
            return;
        }
        receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                int code = intent.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
                if (code == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                    Intent confirm = (Intent) intent.getParcelableExtra(Intent.EXTRA_INTENT);
                    if (confirm != null) {
                        confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        context.startActivity(confirm);
                        status = "confirm";
                    } else {
                        status = "failed: Android did not show its install screen";
                    }
                } else if (code == PackageInstaller.STATUS_SUCCESS) {
                    status = "success";
                } else {
                    String message = intent.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE);
                    status = "failed: " + code + (message != null ? " " + message : "");
                }
            }
        };
        IntentFilter filter = new IntentFilter(ACTION);
        if (Build.VERSION.SDK_INT >= 33) {
            context.registerReceiver(receiver, filter, Context.RECEIVER_NOT_EXPORTED);
        } else {
            context.registerReceiver(receiver, filter);
        }
    }
}
