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
