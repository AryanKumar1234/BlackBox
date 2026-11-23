#!/usr/bin/env python3
"""Apply the VXPosed launch fixes to the freshly cloned engine source.

Usage: patch_engine.py <engine-dir>

Every patch is tolerant: if the upstream text has drifted, the change is
skipped with a warning instead of failing the build, except for the version
bump which must always land.
"""
import re
import sys
from pathlib import Path

root = Path(sys.argv[1] if len(sys.argv) > 1 else "src")


def read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def write(p, text):
    p.write_text(text, encoding="utf-8")


def note(msg):
    print(f"[patch] {msg}")


# ---------------------------------------------------------------- version bump
gradle = root / "app" / "build.gradle"
text = read(gradle)
text = re.sub(r"versionCode\s+\d+", "versionCode 3", text, count=1)
text = re.sub(r'versionName\s+"[^"]*"', 'versionName "1.2.0"', text, count=1)
write(gradle, text)
if "versionCode 3" not in text or '"1.2.0"' not in text:
    sys.exit("version bump failed - app/build.gradle layout changed")
note("app version -> 1.2.0 (3)")

# --------------------------------------------------- largeHeap for guest apps
manifest = root / "app" / "src" / "main" / "AndroidManifest.xml"
text = read(manifest)
if "android:largeHeap" not in text:
    new = text.replace("<application", '<application\n        android:largeHeap="true"', 1)
    if new != text:
        write(manifest, new)
        note("application: android:largeHeap=true")
    else:
        note("WARN: <application> tag not found, largeHeap not set")
else:
    note("largeHeap already present")

# ------------------------------------------- UI callback: drop ACTION_MAIN gate
core = root / "lib" / "src" / "main" / "java" / "com" / "lody" / "virtual" / "client" / "core" / "VirtualCore.java"
if core.exists():
    text = read(core)
    patterns = [
        """
        // only for launch intent.
        if (!Intent.ACTION_MAIN.equals(intent.getAction())) {
            return null;
        }""",
        "if (!Intent.ACTION_MAIN.equals(intent.getAction())) {\n            return null;\n        }",
    ]
    applied = False
    for pat in patterns:
        if pat in text:
            text = text.replace(pat, "\n        // The loading screen needs the callback no matter which action\n        // the launcher intent uses.", 1)
            applied = True
            break
    if applied:
        write(core, text)
        note("VirtualCore.getUiCallback: ACTION_MAIN restriction removed")
    else:
        note("WARN: getUiCallback gate not found (upstream changed), skipped")
else:
    note("WARN: VirtualCore.java not found, skipped")

print("[patch] done")
