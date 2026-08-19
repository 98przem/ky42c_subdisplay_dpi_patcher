#!/usr/bin/env python3
"""
Patches SubLcdDrawer.smali (from services.jar, classes2.dex) so the
sub-display's LayoutInflater always uses 240dpi instead of whatever
your global wm density override is set to. Fixes clock/battery/manner
mode/signal layout breaking on the KY-42C flip screen when you change
main-screen DPI.

    python3 patch_subdisplay_dpi_en.py path/to/SubLcdDrawer.smali

Patch your own dumped services.jar, don't share the patched jar itself.
"""

import sys
from pathlib import Path

METHOD_HEADER = ".method public wakeUp(Ljava/util/Locale;ZI)V"

OLD_REGISTERS = "    .registers 7\n"
NEW_REGISTERS = "    .registers 9\n"

# Original code: builds the LayoutInflater straight from the raw
# system_server Context, which is subject to the global density
# override.
OLD_BLOCK = """    .line 109
    :cond_90
    iget-object p1, p0, Ljp/kyocera/server/sublcd/draw/SubLcdDrawer;->mContext:Landroid/content/Context;

    invoke-static {p1}, Landroid/view/LayoutInflater;->from(Landroid/content/Context;)Landroid/view/LayoutInflater;

    move-result-object p1

    iput-object p1, p0, Ljp/kyocera/server/sublcd/draw/SubLcdDrawer;->mInflater:Landroid/view/LayoutInflater;
"""

# v3/v4 are two fresh local registers freed up by .registers 7 -> 9.
NEW_BLOCK = """    .line 109
    :cond_90
    iget-object p1, p0, Ljp/kyocera/server/sublcd/draw/SubLcdDrawer;->mContext:Landroid/content/Context;

    new-instance v3, Landroid/content/res/Configuration;

    invoke-direct {v3}, Landroid/content/res/Configuration;-><init>()V

    const/16 v4, 0xf0

    iput v4, v3, Landroid/content/res/Configuration;->densityDpi:I

    invoke-virtual {p1, v3}, Landroid/content/Context;->createConfigurationContext(Landroid/content/res/Configuration;)Landroid/content/Context;

    move-result-object p1

    invoke-static {p1}, Landroid/view/LayoutInflater;->from(Landroid/content/Context;)Landroid/view/LayoutInflater;

    move-result-object p1

    iput-object p1, p0, Ljp/kyocera/server/sublcd/draw/SubLcdDrawer;->mInflater:Landroid/view/LayoutInflater;
"""


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python3 patch_subdisplay_dpi.py path/to/SubLcdDrawer.smali")
        return 1

    path = Path(sys.argv[1]).expanduser()
    text = path.read_text()

    if METHOD_HEADER not in text:
        print("ERROR: couldn't find the wakeUp() method header - this file "
              "might not be the one you expect, or it's already patched. "
              "Aborting, nothing written.")
        return 1

    # Scope the register-count patch to the wakeUp method only, so we
    # don't touch ".registers 7" lines belonging to unrelated methods
    # elsewhere in the same file.
    method_start = text.index(METHOD_HEADER)
    method_end = text.index(".end method", method_start)
    method_body = text[method_start:method_end]

    if method_body.count(OLD_REGISTERS) != 1:
        print(f"ERROR: expected exactly 1 occurrence of '.registers 7' inside "
              f"wakeUp(), found {method_body.count(OLD_REGISTERS)}. Aborting, "
              f"nothing written.")
        return 1

    if method_body.count(OLD_BLOCK) != 1:
        print(f"ERROR: expected exactly 1 match for the original code block, "
              f"found {method_body.count(OLD_BLOCK)}. Your file might be "
              f"formatted differently (e.g. a different baksmali version) - "
              f"aborting, nothing written.")
        return 1

    patched_method_body = method_body.replace(OLD_REGISTERS, NEW_REGISTERS, 1)
    patched_method_body = patched_method_body.replace(OLD_BLOCK, NEW_BLOCK, 1)

    new_text = text[:method_start] + patched_method_body + text[method_end:]

    backup_path = path.with_suffix(path.suffix + ".bak")
    if not backup_path.exists():
        backup_path.write_text(text)
        print(f"Backup written to: {backup_path}")

    path.write_text(new_text)
    print(f"Patched: {path}")
    print("Change: the sub-display LayoutInflater now always uses 240dpi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
