#!/usr/bin/env python3
"""Apply the VXPosed launch fixes to the freshly cloned engine source.

Usage: patch_engine.py <engine-dir>

The important one is the loading screen: it used to finish() straight from a
binder thread and to wait forever for a callback that is easily lost, which is
exactly the endless "Opening ..." screen. We now finish on the UI thread and
watch the cloned process ourselves.

Patches are tolerant: unknown upstream text is reported and skipped, only the
version bump is mandatory.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "src")
here = Path(__file__).resolve().parent

warnings = []


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def note(msg):
    print(f"[patch] {msg}")


def swap(text, old, new, label):
    """Replace exactly once; returns (text, applied)."""
    if old not in text:
        warnings.append(f"{label}: anchor not found")
        return text, False
    note(label)
    return text.replace(old, new, 1), True


# ---------------------------------------------------------------- version bump
gradle = root / "app" / "build.gradle"
text = read(gradle)
text = re.sub(r"versionCode\s+\d+", "versionCode 3", text, count=1)
text = re.sub(r'versionName\s+"[^"]*"', 'versionName "1.2.0"', text, count=1)
gradle.write_text(text, encoding="utf-8")
if "versionCode 3" not in text or '"1.2.0"' not in text:
    sys.exit("version bump failed - app/build.gradle layout changed")
note("app version -> 1.2.0 (3)")

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

# --------------------------------------------- LoadingActivity: finish on UI thread
loading = root / "app" / "src" / "main" / "java" / "io" / "virtualapp" / "home" / "LoadingActivity.java"
if loading.exists():
    text = read(loading)
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
    text, ok2 = swap(
        text,
        """    private void launchActivity(Intent intent, int userId) {
        try {
            VActivityManager.get().startActivity(intent, userId);
        }""",
        """    private void launchActivity(Intent intent, int userId) {
        try {
            VActivityManager.get().startActivity(intent, userId);
            startOpenWatchdog(userId);
        }""",
        "LoadingActivity: start the open watchdog right after launching",
    )
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
    if ok1 and ok2 and ok3:
        part = (here / "watchdog.java.part").read_text(encoding="utf-8")
        stripped = text.rstrip()
        if not stripped.endswith("}"):
            sys.exit("LoadingActivity.java does not end with a closing brace")
        text = stripped[:-1] + "\n" + part + "}\n"
        note("LoadingActivity: watchdog injected")
    else:
        warnings.append("LoadingActivity: watchdog NOT injected (anchors changed)")
    loading.write_text(text, encoding="utf-8")
else:
    sys.exit("LoadingActivity.java not found in the engine source")

# ------------------------------------------- UI callback: drop ACTION_MAIN gate
core = root / "lib" / "src" / "main" / "java" / "com" / "lody" / "virtual" / "client" / "core" / "VirtualCore.java"
if core.exists():
    text = read(core)
    gate = """        // only for launch intent.
        if (!Intent.ACTION_MAIN.equals(intent.getAction())) {
            return null;
        }"""
    text, applied = swap(
        text,
        gate,
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
