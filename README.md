# ky42c-subdisplay-dpi-fix

Changing global DPI (`wm density`) on the KY-42C breaks the sub-display
layout - clock, battery, manner mode, signal all get misplaced when
you view them via the camera/manner mode button.

Turns out the sub-display isn't a real Android Display. The status
view gets rendered inside system_server itself
(`services.jar` -> `jp.kyocera.server.sublcd.draw.SubLcdDrawer`), and
its LayoutInflater is built from the same context your global density
override touches. This patches `SubLcdDrawer.wakeUp()` so it always
uses 240dpi (the panel's actual density) via
`createConfigurationContext()`, no matter what `wm density` is set to
globally.

Ships as a systemless Magisk module. Only `services.jar` gets
overlaid at boot, nothing on `/system` is touched directly.

## Usage

Need `adb`, `java`, `curl`, root (Magisk), USB debugging on.

```
python3 ky42c_subdisplay_dpi_patcher.py
```

Pulls your own services.jar, disassembles it, patches it, rebuilds
the jar, packages a Magisk module zip, pushes it to
`/sdcard/Download/`. Downloads baksmali/smali on its own if you don't
have them. On the phone: Magisk app -> Modules -> Install from
storage, reboot when it asks.

## Doing it by hand

```
adb pull /system/framework/services.jar
unzip services.jar classes2.dex

# baksmali/smali: https://github.com/baksmali/smali/releases
# tag 3.0.9, baksmali-3.0.9-fat.jar / smali-3.0.9-fat.jar
java -jar baksmali.jar disassemble classes2.dex -o classes2_smali

python3 patch_subdisplay_dpi_en.py classes2_smali/jp/kyocera/server/sublcd/draw/SubLcdDrawer.smali

java -jar smali.jar assemble classes2_smali -o classes2_patched.dex

cp services.jar services_patched.jar
zip -d services_patched.jar classes2.dex
cp classes2_patched.dex classes2.dex
zip -j services_patched.jar classes2.dex
```

Package as a module:

```
mkdir -p module/system/framework
cp services_patched.jar module/system/framework/services.jar
cat > module/module.prop << EOF
id=subdisplay_dpi_fix
name=SubLCD DPI Fix
version=v1
versionCode=1
author=your-name
description=Locks sub-display LayoutInflater to 240dpi. Built against: $(adb shell getprop ro.build.fingerprint)
EOF
cd module && zip -r ../subdisplay_dpi_fix.zip module.prop system && cd ..

adb push subdisplay_dpi_fix.zip /sdcard/Download/
```

Then Magisk app -> Modules -> Install from storage.

## This is build-specific

Don't install a module built on someone else's phone. classes2.dex
has to match the rest of services.jar on your exact firmware version.
The zip's module.prop has the build fingerprint it was patched
against - compare before installing:

```
adb shell getprop ro.build.fingerprint
```

Doesn't match what's in module.prop, don't install it. And disable
the module before taking a system OTA, then re-patch against the new
services.jar afterward.

## If it breaks

`adb shell magisk --remove-modules` disables all modules and reboots,
works even if the phone doesn't fully boot since adb starts early.
Magisk also disables modules on its own after a few failed boots.

No guarantees, reverse-engineered from one device on one build. Read
the diff before trusting it on your only phone.
