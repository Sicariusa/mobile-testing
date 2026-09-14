# Setting up an Android device or emulator

This runner needs a real Android target for a live run. This guide installs the
SDK tools, connects a device (or starts an emulator), installs Tesseract for
OCR, and initialises uiautomator2. When you're done,
`python cli.py --check-env` should report **Live runner: READY**.

> **Cloud/container note.** An Android **emulator needs hardware
> virtualization (KVM)**. A typical cloud container has no `/dev/kvm` and no CPU
> virtualization flags, so the emulator cannot start there (software TCG
> emulation is far too slow to be usable). Run live tests on a machine with KVM
> (a Linux host/VM with nested virt) or on **a physical device** attached over
> USB / Wi-Fi. The device-independent core and the whole test suite run fine
> anywhere.

---

## 0. Prerequisites

- **Java (JDK 17+)** — required by the SDK command-line tools.
  ```bash
  java -version
  ```
- **Python 3.11+** and the project deps:
  ```bash
  pip install -r requirements.txt
  ```

---

## 1. Install the Android SDK command-line tools

Download "Command line tools only" from
<https://developer.android.com/studio#command-tools> and unzip so you have
`cmdline-tools/latest/`.

```bash
export ANDROID_HOME="$HOME/Android/sdk"
mkdir -p "$ANDROID_HOME/cmdline-tools"
# unzip the downloaded tools so this path exists:
#   $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager
export PATH="$ANDROID_HOME/cmdline-tools/latest/bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$PATH"
```

Add those `export` lines to your shell profile (`~/.bashrc` / `~/.zshrc`).

Install the packages the runner uses:

```bash
sdkmanager --licenses            # accept all
sdkmanager "platform-tools"      # provides: adb
sdkmanager "build-tools;34.0.0"  # provides: aapt / aapt2
sdkmanager "platforms;android-34"
# only needed for the emulator path:
sdkmanager "emulator" "system-images;android-34;google_apis;x86_64"
```

Verify:

```bash
adb --version
aapt version          # or: aapt2 version   (either satisfies the runner)
```

> On Debian/Ubuntu you can instead get `adb`, `aapt`, and `tesseract` straight
> from apt (`sudo apt-get install -y adb aapt tesseract-ocr`); the SDK
> `emulator` still comes from `sdkmanager`.

---

## 2a. Emulator path (needs KVM)

Check virtualization is available:

```bash
ls -l /dev/kvm && egrep -c '(vmx|svm)' /proc/cpuinfo
```

Create and launch a headless AVD:

```bash
avdmanager create avd -n qa -k "system-images;android-34;google_apis;x86_64" -d pixel_6
emulator -avd qa -no-window -no-audio -no-boot-anim -gpu swiftshader_indirect &
adb wait-for-device
```

## 2b. Physical device path (no KVM needed)

1. On the phone: **Settings → About phone → tap Build number 7×** to enable
   Developer Options.
2. **Settings → Developer options → enable USB debugging.**
3. Plug in over USB and authorize the host when prompted.
4. For wireless: `adb tcpip 5555` then `adb connect <phone-ip>:5555`.

Confirm the target is visible:

```bash
adb devices          # should list one line ending in "device" (not "unauthorized")
```

---

## 3. Initialise uiautomator2

uiautomator2 installs a small helper agent (ATX) on the device the first time:

```bash
python -m uiautomator2 init
```

Quick smoke test:

```bash
python - <<'PY'
import uiautomator2 as u2
d = u2.connect()          # first ADB device
print(d.info)             # prints device info if the agent is up
PY
```

---

## 4. Install Tesseract (OCR)

The `pytesseract` Python package needs the native `tesseract` binary.

| OS            | Command                                         |
|---------------|-------------------------------------------------|
| Debian/Ubuntu | `sudo apt-get install -y tesseract-ocr`         |
| macOS (brew)  | `brew install tesseract`                        |
| Windows       | Install the UB-Mannheim build, add it to PATH   |

Verify:

```bash
tesseract --version
```

---

## 5. Confirm and run

```bash
python cli.py --check-env      # expect: Live runner: READY
python cli.py --apk app.apk --test testcases/login.yaml
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `Live runner: BLOCKED`, device MISSING | no target connected | start an AVD or connect a phone (§2) |
| `adb devices` shows `unauthorized` | host not authorized | replug and accept the RSA prompt on the device |
| `adb devices` shows `offline` | stale adb / booting | `adb kill-server && adb start-server`; wait for boot |
| emulator won't start / very slow | no KVM | use a KVM-capable host or a physical device (§2b) |
| `Neither aapt nor aapt2 found` | build-tools not on PATH | `sdkmanager "build-tools;34.0.0"`; add to PATH |
| OCR asserts always fail | `tesseract` missing | install it (§4) and re-check `tesseract --version` |
| uiautomator2 can't connect | ATX agent not installed | `python -m uiautomator2 init` |

When in doubt, `python cli.py --check-env` tells you exactly what is missing and
whether it is required for a live run.
