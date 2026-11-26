"""Patch the Bubblewrap-generated Android project so the app always opens in Google Chrome when it is installed.

Why: notifications in a Trusted Web Activity only reach the app when the browser behind it supports notification
delegation. Chrome does; Samsung Internet (the default browser on many Samsung phones) does not, so the APK could
never get the notification permission there. With this patch the app asks for permission like a normal app.
If Chrome is missing or disabled, the default browser is used as before.

Run from the android/ folder after `bubblewrap update` and before `bubblewrap build`.
"""
import pathlib
import re
import sys

CHROME = "com.android.chrome"

root = pathlib.Path("app/src/main")
act = next(root.glob("java/**/LauncherActivity.java"), None)
if act is None:
    sys.exit("LauncherActivity.java not found - run after bubblewrap update")

src = act.read_text()
if "createTwaLauncher" not in src:
    method = f'''
    @Override
    protected com.google.androidbrowserhelper.trusted.TwaLauncher createTwaLauncher() {{
        // Open in Chrome when available: it delegates web notifications to this app (other browsers cannot).
        try {{
            android.content.pm.ApplicationInfo info = getPackageManager().getApplicationInfo("{CHROME}", 0);
            if (info.enabled) {{
                return new com.google.androidbrowserhelper.trusted.TwaLauncher(this, "{CHROME}");
            }}
        }} catch (android.content.pm.PackageManager.NameNotFoundException ignored) {{
        }}
        return super.createTwaLauncher();
    }}
'''
    idx = src.rstrip().rfind("}")
    src = src[:idx] + method + "}\n"
    act.write_text(src)
    print(f"patched {act}")

man = root / "AndroidManifest.xml"
m = man.read_text()
if f'<package android:name="{CHROME}"' not in m:
    m = re.sub(r"(<application\b)", f'<queries><package android:name="{CHROME}" /></queries>\n    \\1', m, count=1)
    man.write_text(m)
    print(f"patched {man}")

# ---- notifications (owner, 26 Nov 2026: testers could not turn notifications on in the APK) -------------------
# Google's helper library marks "asked" the first time the website asks; one dismissed / declined Android question then
# reads as "blocked" on the website for good, and the website can never ask again. Two fixes inside the app:
#  1. On Android 13+ the app asks Android itself once, at its first start after install / update, before the site loads
#     (the normal "Allow Crypto AI to send you notifications?" question).
#  2. A "Turn on notifications" link on the website (cryptoai://notifications) opens NotifySettingsActivity: it asks
#     again while Android still allows it, otherwise it opens this app's notification switch in the phone settings, and
#     then returns to the app's Settings page (…/settings?notify=on|off), where the website registers the phone.
src = act.read_text()
pkg = re.search(r"^\s*package\s+([\w.]+)\s*;", src, re.M).group(1)
if "ciaNotifyOff" not in src:
    method = '''
    private static final int CIA_NOTIFY_REQ = 4711;
    private static final int CIA_SETTINGS_REQ = 4714;
    private static final String CIA_PERM = "android.permission.POST_NOTIFICATIONS";
    private boolean ciaWaiting = false;

    private android.content.SharedPreferences ciaPrefs() {
        return getSharedPreferences("cia_notify", MODE_PRIVATE);
    }

    private boolean ciaGranted() {
        if (Build.VERSION.SDK_INT >= 33) {
            return checkSelfPermission(CIA_PERM) == android.content.pm.PackageManager.PERMISSION_GRANTED;
        }
        return true;
    }

    /** Notifications off for this app: the permission, the app's switch, or one of its notification types. */
    private boolean ciaNotifyOff() {
        if (!ciaGranted()) return true;
        if (Build.VERSION.SDK_INT < 24) return false;
        android.app.NotificationManager nm = (android.app.NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) return false;
        if (!nm.areNotificationsEnabled()) return true;
        if (Build.VERSION.SDK_INT >= 26) {
            for (android.app.NotificationChannel ch : nm.getNotificationChannels()) {
                if (ch.getImportance() == android.app.NotificationManager.IMPORTANCE_NONE) return true;
            }
        }
        return false;
    }

    @Override
    protected boolean shouldLaunchImmediately() {
        android.content.SharedPreferences prefs = ciaPrefs();
        // 1. Android 13+: the first start after install / update asks Android directly (before the website loads)
        if (Build.VERSION.SDK_INT >= 33 && !ciaGranted() && !prefs.getBoolean("asked_at_launch_v1", false)) {
            prefs.edit().putBoolean("asked_at_launch_v1", true).apply();
            ciaWaiting = true;
            requestPermissions(new String[]{CIA_PERM}, CIA_NOTIFY_REQ);
            return false;
        }
        // 2. still off: offer to turn them on (at most once a day after "Not now")
        long later = prefs.getLong("later_until", 0L);
        if (ciaNotifyOff() && System.currentTimeMillis() > later) {
            ciaWaiting = true;
            new android.app.AlertDialog.Builder(this)
                    .setTitle("Notifications are off")
                    .setMessage("Turn them on to get new signals, target hits and stop alerts.")
                    .setCancelable(false)
                    .setPositiveButton("Turn on", (d, w) -> ciaTurnOn())
                    .setNegativeButton("Not now", (d, w) -> {
                        ciaPrefs().edit().putLong("later_until", System.currentTimeMillis() + 86400000L).apply();
                        ciaLaunch();
                    })
                    .show();
            return false;
        }
        return true;
    }

    private void ciaTurnOn() {
        if (Build.VERSION.SDK_INT >= 33 && !ciaGranted() && shouldShowRequestPermissionRationale(CIA_PERM)) {
            requestPermissions(new String[]{CIA_PERM}, CIA_NOTIFY_REQ);   // Android still allows asking
            return;
        }
        ciaOpenSettings();
    }

    private void ciaOpenSettings() {
        android.content.Intent i;
        if (Build.VERSION.SDK_INT >= 26) {
            i = new android.content.Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS);
            i.putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, getPackageName());
        } else {
            i = new android.content.Intent(android.provider.Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.fromParts("package", getPackageName(), null));
        }
        try {
            startActivityForResult(i, CIA_SETTINGS_REQ);
        } catch (Exception e) {
            ciaLaunch();
        }
    }

    private void ciaLaunch() {
        if (!ciaWaiting) return;
        ciaWaiting = false;
        launchTwa();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != CIA_NOTIFY_REQ) return;
        // allowed but a notification type is still off: straight to the switch
        if (ciaGranted() && ciaNotifyOff()) { ciaOpenSettings(); return; }
        ciaLaunch();
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, android.content.Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == CIA_SETTINGS_REQ) ciaLaunch();
    }
'''
    idx = src.rstrip().rfind("}")
    src = src[:idx] + method + "}\n"
    act.write_text(src)
    print(f"patched {act} (ask at launch)")

notify = act.parent / "NotifySettingsActivity.java"
notify.write_text(f'''package {pkg};

import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;

import android.app.NotificationManager;

/** Opened by the website's "Turn on notifications" link (cryptoai://notifications). Asks Android again while it still
 *  allows that, otherwise opens this app's notification switch, then goes back to the app's Settings page. */
public class NotifySettingsActivity extends Activity {{
    private static final String PERM = "android.permission.POST_NOTIFICATIONS";
    private static final int ASK = 4712;
    private static final int SETTINGS = 4713;

    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        if (savedInstanceState != null) return;            // recreated while waiting: the result still comes here
        // the phone allows notifications, yet the website reads "blocked": the browser's own setting for this site is
        // off (Android 12 and older have no app question at all) - open exactly that page (Site settings → Allow)
        if (enabled()) {{ openSiteSettings(); return; }}
        if (Build.VERSION.SDK_INT >= 33 && !granted()) {{
            requestPermissions(new String[]{{PERM}}, ASK);
            return;
        }}
        openSettings();                                     // allowed, but a notification type is switched off
    }}

    /** The app's switch AND every notification type (channel) it has: one switched-off channel (e.g. the website's
     *  "General") makes the website read "blocked" although the app itself is allowed. */
    private boolean enabled() {{
        if (Build.VERSION.SDK_INT < 24) return true;
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (nm == null) return true;
        if (!nm.areNotificationsEnabled()) return false;
        if (Build.VERSION.SDK_INT >= 26) {{
            for (android.app.NotificationChannel ch : nm.getNotificationChannels()) {{
                if (ch.getImportance() == NotificationManager.IMPORTANCE_NONE) return false;
            }}
        }}
        return true;
    }}

    /** What Android says, sent back to the website for the owner's report: sdk, app switch, each channel's importance,
     *  the browser that runs the app. */
    private String info() {{
        StringBuilder b = new StringBuilder("sdk" + Build.VERSION.SDK_INT);
        try {{
            NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
            if (nm != null && Build.VERSION.SDK_INT >= 24) b.append(" on").append(nm.areNotificationsEnabled() ? 1 : 0);
            if (nm != null && Build.VERSION.SDK_INT >= 26) {{
                for (android.app.NotificationChannel ch : nm.getNotificationChannels()) {{
                    b.append(" ").append(ch.getId()).append(":").append(ch.getImportance());
                }}
            }}
        }} catch (Exception e) {{ b.append(" err"); }}
        b.append(siteWasOpened ? " site" : "");
        return b.length() > 300 ? b.substring(0, 300) : b.toString();
    }}

    private boolean siteWasOpened = false;

    private boolean granted() {{
        if (Build.VERSION.SDK_INT >= 33) {{
            return checkSelfPermission(PERM) == android.content.pm.PackageManager.PERMISSION_GRANTED;
        }}
        return true;
    }}

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {{
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != ASK) return;
        if (enabled()) {{ back(); return; }}
        // allowed but a type is off, or no question was shown (Android blocks it after two "Don't allow"): the switch
        if (granted() || (Build.VERSION.SDK_INT >= 33 && !shouldShowRequestPermissionRationale(PERM))) openSettings();
        else back();
    }}

    private void openSiteSettings() {{
        try {{
            Intent i = new Intent();
            i.setClassName(getPackageName(), "com.google.androidbrowserhelper.trusted.ManageDataLauncherActivity");
            startActivity(i);
            siteOpen = true;                                 // stay; onRestart = the person came back from that page
            siteWasOpened = true;
        }} catch (Exception e) {{
            back();
        }}
    }}

    private boolean siteOpen = false;

    /** Back from the browser's site page: restart the app fully, so the browser reads the new setting (a plain
     *  return keeps the old "blocked" answer in the open page). */
    @Override
    protected void onRestart() {{
        super.onRestart();
        if (siteOpen) {{ siteOpen = false; back(); }}
    }}

    private void openSettings() {{
        Intent i;
        if (Build.VERSION.SDK_INT >= 26) {{
            i = new Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS);
            i.putExtra(Settings.EXTRA_APP_PACKAGE, getPackageName());
        }} else {{
            i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", getPackageName(), null));
        }}
        try {{
            startActivityForResult(i, SETTINGS);
        }} catch (Exception e) {{
            back();
        }}
    }}

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {{
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == SETTINGS) back();
    }}

    private void back() {{
        Intent t = new Intent(this, LauncherActivity.class);
        t.setAction(Intent.ACTION_VIEW);
        t.setData(Uri.parse("https://" + getString(R.string.hostName) + "/settings?notify=" + (enabled() ? "on" : "off") + "&d=" + Uri.encode(info())));
        // a fresh start (not just a page reload): the browser re-reads the app's notification permission only then
        t.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(t);
        finish();
    }}
}}
''')
print(f"wrote {notify}")

m = man.read_text()
if "NotifySettingsActivity" not in m:
    entry = '''
        <activity android:name=".NotifySettingsActivity"
            android:exported="true"
            android:excludeFromRecents="true"
            android:theme="@android:style/Theme.Translucent.NoTitleBar">
            <intent-filter>
                <action android:name="android.intent.action.VIEW" />
                <category android:name="android.intent.category.DEFAULT" />
                <category android:name="android.intent.category.BROWSABLE" />
                <data android:scheme="cryptoai" android:host="notifications" />
            </intent-filter>
        </activity>
'''
    i = m.rfind("</application>")
    m = m[:i] + entry + "    " + m[i:]
    man.write_text(m)
    print(f"patched {man} (NotifySettingsActivity)")
