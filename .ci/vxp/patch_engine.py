#!/usr/bin/env python3
"""Apply the VXPosed launch fixes to the freshly cloned engine source.

Usage: patch_engine.py <engine-dir>

Two root causes are addressed here:

1. The loading screen waited forever for a callback from the cloned process and
   called finish() from a binder thread. It is now finished on the UI thread,
   and a watchdog takes over if the callback never arrives.

2. VActivityManager.startActivity() is a synchronous call into the engine's
   service process and can block for a very long time (it waits for the cloned
   process to finish binding). Running it on the UI thread froze the loading
   screen so badly that nothing - not even the watchdog - could ever run.
   It is now called from a worker thread.

Unknown upstream text is reported and skipped; only the version bump is
mandatory.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
here = Path(__file__).resolve().parent

warnings = []

NEW_LAUNCH = """    private void launchActivity(final Intent intent, final int userId) {
        startOpenWatchdog(userId);
        mLaunchInFlight = true;
        new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    VActivityManager.get().startActivity(intent, userId);
                } catch (final Throwable e) {
                    VLog.e(TAG, "start activity failed:", e);
                    mOpenWatchdog.post(new Runnable() {
                        @Override
                        public void run() {
                            if (!isFinishing()) {
                                showOpenFailure(appModel.packageName, false);
                            }
                        }
                    });
                } finally {
                    mLaunchInFlight = false;
                }
            }
        }, "vxp-launch").start();
    }
"""


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def note(msg):
    print(f"[patch] {msg}")


def swap(text, old, new, label):
    if old not in text:
        warnings.append(f"{label}: anchor not found")
        return text, False
    note(label)
    return text.replace(old, new, 1), True


# ---------------------------------------------------------------- version bump
gradle = root / "app" / "build.gradle"
text = read(gradle)
text = re.sub(r"versionCode\s+\d+", "versionCode 4", text, count=1)
text = re.sub(r'versionName\s+"[^"]*"', 'versionName "1.3.0"', text, count=1)
gradle.write_text(text, encoding="utf-8")
if "versionCode 4" not in text or '"1.3.0"' not in text:
    sys.exit("version bump failed - app/build.gradle layout changed")
note("app version -> 1.3.0 (4)")

# --------------------------------------------------- largeHeap for guest apps
manifest = root / "app" / "src" / "main" / "AndroidManifest.xml"
text = read(manifest)
if "android:largeHeap" in text:
    note("largeHeap already present")
elif "<application" in text:
    manifest.write_text(
        text.replace("<application", '<application\n        android:largeHeap="true"', 1),
        encoding="utf-8",
    )
    note("application: android:largeHeap=true")
else:
    warnings.append("largeHeap: <application> tag not found")

# ------------------------------------------------------- LoadingActivity fixes
loading = root / "app" / "src" / "main" / "java" / "io" / "virtualapp" / "home" / "LoadingActivity.java"
if not loading.exists():
    sys.exit("LoadingActivity.java not found in the engine source")

text = read(loading)

# 1. finish on the UI thread
text, ok1 = swap(
    text,
    """        public void onAppOpened(String packageName, int userId) throws RemoteException {
            finish();
        }""",
    """        public void onAppOpened(String packageName, int userId) throws RemoteException {
            runOnUiThread(new Runnable() {
                @Override
                public void run() {
                    stopOpenWatchdog();
                    if (!isFinishing()) {
                        finish();
                    }
                }
            });
        }""",
    "LoadingActivity: onAppOpened finishes on the UI thread",
)

# 2. never call into the engine on the UI thread
match = re.search(
    r"    private void launchActivity\(Intent intent, int userId\) \{.*?\n    \}\n",
    text,
    re.S,
)
if match:
    text = text[: match.start()] + NEW_LAUNCH + text[match.end():]
    note("LoadingActivity: engine launch moved off the UI thread")
else:
    warnings.append("LoadingActivity: launchActivity() not found")

# 3. stop the watchdog with the activity
text, ok3 = swap(
    text,
    """    @Override
    protected void onStop() {""",
    """    @Override
    protected void onDestroy() {
        stopOpenWatchdog();
        super.onDestroy();
    }

    @Override
    protected void onStop() {""",
    "LoadingActivity: stop the watchdog in onDestroy",
)

if ok1 and ok3 and match:
    part = (here / "watchdog.java.part").read_text(encoding="utf-8")
    stripped = text.rstrip()
    if not stripped.endswith("}"):
        sys.exit("LoadingActivity.java does not end with a closing brace")
    text = stripped[:-1] + "\n" + part + "}\n"
    note("LoadingActivity: watchdog injected")
else:
    warnings.append("LoadingActivity: watchdog NOT injected (anchors changed)")
loading.write_text(text, encoding="utf-8")

# ------------------------------------------- UI callback: drop ACTION_MAIN gate
core = root / "lib" / "src" / "main" / "java" / "com" / "lody" / "virtual" / "client" / "core" / "VirtualCore.java"
if core.exists():
    text = read(core)
    text, applied = swap(
        text,
        """        // only for launch intent.
        if (!Intent.ACTION_MAIN.equals(intent.getAction())) {
            return null;
        }""",
        """        // The loading screen needs its callback no matter which action the
        // launcher intent uses.""",
        "VirtualCore.getUiCallback: ACTION_MAIN restriction removed",
    )
    if applied:
        core.write_text(text, encoding="utf-8")
else:
    warnings.append("VirtualCore.java not found")

for w in warnings:
    note(f"WARN: {w}")
print("[patch] done")
