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
if "ciaAskAtLaunch" not in src:
    method = '''
    private static final int CIA_NOTIFY_REQ = 4711;
    private boolean ciaWaiting = false;

    private boolean ciaAskAtLaunch() {
        if (Build.VERSION.SDK_INT < 33) return false;
        if (checkSelfPermission("android.permission.POST_NOTIFICATIONS")
                == android.content.pm.PackageManager.PERMISSION_GRANTED) return false;
        android.content.SharedPreferences prefs = getSharedPreferences("cia_notify", MODE_PRIVATE);
        if (prefs.getBoolean("asked_at_launch_v1", false)) return false;
        prefs.edit().putBoolean("asked_at_launch_v1", true).apply();
        return true;
    }

    @Override
    protected boolean shouldLaunchImmediately() {
        // Android 13+: ask for notifications once, before the website loads (the question would otherwise only come
        // from the website, where one dismissed question blocks it for good)
        if (Build.VERSION.SDK_INT >= 33 && ciaAskAtLaunch()) {
            ciaWaiting = true;
            requestPermissions(new String[]{"android.permission.POST_NOTIFICATIONS"}, CIA_NOTIFY_REQ);
            return false;
        }
        return true;
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == CIA_NOTIFY_REQ && ciaWaiting) {
            ciaWaiting = false;
            launchTwa();
        }
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
        if (enabled()) {{ back(); return; }}
        if (Build.VERSION.SDK_INT >= 33) {{
            requestPermissions(new String[]{{PERM}}, ASK);
            return;
        }}
        openSettings();
    }}

    private boolean enabled() {{
        if (Build.VERSION.SDK_INT < 24) return true;
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        return nm == null || nm.areNotificationsEnabled();
    }}

    @Override
    public void onRequestPermissionsResult(int requestCode, String[] permissions, int[] grantResults) {{
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode != ASK) return;
        if (enabled()) {{ back(); return; }}
        // no question was shown (Android blocks it after two "Don't allow"): go to the switch instead
        if (Build.VERSION.SDK_INT >= 33 && !shouldShowRequestPermissionRationale(PERM)) openSettings();
        else back();
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
        t.setData(Uri.parse("https://" + getString(R.string.hostName) + "/settings?notify=" + (enabled() ? "on" : "off")));
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
