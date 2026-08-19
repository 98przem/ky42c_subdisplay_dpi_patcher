#!/usr/bin/env python3
"""
ky42c_subdisplay_dpi_patcher.py

End-to-end, interactive tool that:
  1. pulls services.jar from a connected device over adb
  2. finds and disassembles the dex containing SubLcdDrawer
  3. patches SubLcdDrawer.wakeUp() to lock the sub-display's
     LayoutInflater to 240dpi, regardless of global wm density
  4. reassembles the dex, rebuilds services.jar
  5. packages a systemless Magisk module zip (tagged with the exact
     build fingerprint of the device it was built on)
  6. pushes the finished zip to /sdcard/Download/ on the device

Requirements on your machine: adb, java (for baksmali/smali - the
script will offer to download the fat jars if missing), python3.

This patches the file pulled from YOUR OWN device. The resulting
module.prop embeds ro.build.fingerprint so anyone else can check
whether it actually matches their build before installing - don't
just hand someone else's build the module built here.

Usage:
    python3 ky42c_subdisplay_dpi_patcher.py
"""

import subprocess
import sys
import shutil
import zipfile
from pathlib import Path

BAKSMALI_URL = "https://github.com/baksmali/smali/releases/download/3.0.9/baksmali-3.0.9-fat.jar"
SMALI_URL = "https://github.com/baksmali/smali/releases/download/3.0.9/smali-3.0.9-fat.jar"

TARGET_CLASS_NEEDLE = b"SubLcdDrawer"
METHOD_HEADER = ".method public wakeUp(Ljava/util/Locale;ZI)V"
OLD_REGISTERS = "    .registers 7\n"
NEW_REGISTERS = "    .registers 9\n"

OLD_BLOCK = """    .line 109
    :cond_90
    iget-object p1, p0, Ljp/kyocera/server/sublcd/draw/SubLcdDrawer;->mContext:Landroid/content/Context;

    invoke-static {p1}, Landroid/view/LayoutInflater;->from(Landroid/content/Context;)Landroid/view/LayoutInflater;

    move-result-object p1

    iput-object p1, p0, Ljp/kyocera/server/sublcd/draw/SubLcdDrawer;->mInflater:Landroid/view/LayoutInflater;
"""

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


def ask(prompt: str, default_yes: bool = True) -> bool:
    suffix = " [Y/n] " if default_yes else " [y/N] "
    reply = input(prompt + suffix).strip().lower()
    if not reply:
        return default_yes
    return reply.startswith("y")


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def die(msg: str) -> None:
    print(f"\n[FATAL] {msg}")
    sys.exit(1)


def check_tool(name: str) -> None:
    if shutil.which(name) is None:
        die(f"'{name}' not found in PATH. Install it and try again.")


def check_device() -> str:
    r = run(["adb", "devices"])
    lines = [l for l in r.stdout.splitlines()[1:] if l.strip() and "device" in l]
    if not lines:
        die("No adb device found. Connect your phone (USB debugging on) and retry.")
    if len(lines) > 1:
        die("Multiple adb devices connected - disconnect all but one and retry.")
    serial = lines[0].split()[0]
    print(f"Device: {serial}")
    return serial


def getprop(prop: str) -> str:
    return run(["adb", "shell", "getprop", prop]).stdout.strip()


def ensure_smali_tools(tools_dir: Path) -> tuple[Path, Path]:
    tools_dir.mkdir(parents=True, exist_ok=True)
    baksmali = tools_dir / "baksmali.jar"
    smali = tools_dir / "smali.jar"
    for path, url in ((baksmali, BAKSMALI_URL), (smali, SMALI_URL)):
        if path.exists():
            continue
        print(f"Downloading {path.name}...")
        r = run(["curl", "-L", "-o", str(path), url])
        if r.returncode != 0 or path.stat().st_size < 100_000:
            die(f"Failed to download {url}")
    return baksmali, smali


def find_target_dex(jar_path: Path, workdir: Path) -> Path:
    with zipfile.ZipFile(jar_path) as z:
        dex_names = [n for n in z.namelist() if n.startswith("classes") and n.endswith(".dex")]
        for name in dex_names:
            data = z.read(name)
            if TARGET_CLASS_NEEDLE in data:
                out = workdir / name
                out.write_bytes(data)
                print(f"Found {TARGET_CLASS_NEEDLE.decode()} in {name}")
                return out
    die(f"Couldn't find any dex containing {TARGET_CLASS_NEEDLE.decode()} in {jar_path.name}")


def patch_smali_file(smali_path: Path) -> None:
    text = smali_path.read_text()
    if METHOD_HEADER not in text:
        die("wakeUp() method header not found - build layout differs from what this script expects.")

    method_start = text.index(METHOD_HEADER)
    method_end = text.index(".end method", method_start)
    method_body = text[method_start:method_end]

    if method_body.count(OLD_REGISTERS) != 1 or method_body.count(OLD_BLOCK) != 1:
        die("Code shape doesn't match expected pattern (different build/baksmali version?). "
            "Aborting without writing anything.")

    patched = method_body.replace(OLD_REGISTERS, NEW_REGISTERS, 1).replace(OLD_BLOCK, NEW_BLOCK, 1)
    smali_path.write_text(text[:method_start] + patched + text[method_end:])
    print("Patched SubLcdDrawer.smali")


def rebuild_jar(original_jar: Path, dex_name: str, patched_dex: Path, out_jar: Path) -> None:
    with zipfile.ZipFile(original_jar) as src, zipfile.ZipFile(out_jar, "w", zipfile.ZIP_DEFLATED) as dst:
        for item in src.infolist():
            if item.filename == dex_name:
                dst.writestr(item, patched_dex.read_bytes())
            else:
                dst.writestr(item, src.read(item.filename))
    print(f"Rebuilt {out_jar.name}")


def build_magisk_zip(patched_jar: Path, out_zip: Path, fingerprint: str) -> None:
    module_prop = (
        "id=subdisplay_dpi_fix\n"
        "name=SubLCD DPI Fix\n"
        "version=v1\n"
        "versionCode=1\n"
        "author=przem\n"
        f"description=Locks sub-display LayoutInflater to 240dpi. Built against: {fingerprint}\n"
    )
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("module.prop", module_prop)
        z.writestr("system/framework/services.jar", patched_jar.read_bytes())
    print(f"Built module: {out_zip}")


def main() -> None:
    check_tool("adb")
    check_tool("java")
    check_tool("curl")

    serial = check_device()
    fingerprint = getprop("ro.build.fingerprint")
    print(f"Build fingerprint: {fingerprint}")

    workdir = Path.cwd() / f"subdisplay_dpi_build_{serial}"
    workdir.mkdir(exist_ok=True)
    tools_dir = Path.cwd() / "smali_tools"

    if not ask(f"Work in {workdir}?"):
        sys.exit(0)

    services_jar = workdir / "services.jar"
    print("\nPulling services.jar...")
    r = run(["adb", "pull", "/system/framework/services.jar", str(services_jar)])
    if r.returncode != 0:
        die(f"adb pull failed:\n{r.stderr}")

    target_dex = find_target_dex(services_jar, workdir)
    dex_name = target_dex.name

    baksmali, smali = ensure_smali_tools(tools_dir)

    smali_dir = workdir / f"{dex_name}_smali"
    print("\nDisassembling...")
    r = run(["java", "-jar", str(baksmali), "disassemble", str(target_dex), "-o", str(smali_dir)])
    if r.returncode != 0:
        die(f"baksmali failed:\n{r.stderr}")

    smali_file = smali_dir / "jp/kyocera/server/sublcd/draw/SubLcdDrawer.smali"
    if not smali_file.exists():
        die(f"Expected file not found: {smali_file}")

    if not ask(f"\nAbout to patch {smali_file.relative_to(workdir)}. Continue?"):
        sys.exit(0)
    patch_smali_file(smali_file)

    patched_dex = workdir / f"{dex_name}.patched"
    print("\nReassembling...")
    r = run(["java", "-jar", str(smali), "assemble", str(smali_dir), "-o", str(patched_dex)])
    if r.returncode != 0:
        die(f"smali assemble failed:\n{r.stderr}")

    patched_jar = workdir / "services_patched.jar"
    rebuild_jar(services_jar, dex_name, patched_dex, patched_jar)

    out_zip = workdir / "ky42c_subdisplay_dpi_fix.zip"
    build_magisk_zip(patched_jar, out_zip, fingerprint)

    print(f"\nModule built for build fingerprint:\n  {fingerprint}")
    if not ask("Push this zip to /sdcard/Download/ on the device now?"):
        print(f"Zip is at: {out_zip}")
        sys.exit(0)

    r = run(["adb", "push", str(out_zip), "/sdcard/Download/"])
    if r.returncode != 0:
        die(f"adb push failed:\n{r.stderr}")

    print(
        "\nDone. On the phone: Magisk app -> Modules -> Install from storage -> "
        "pick the zip from Download, then reboot when prompted.\n"
        "If something goes wrong: `adb shell magisk --remove-modules` disables all "
        "modules and reboots, works even without a full boot."
    )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(1)
