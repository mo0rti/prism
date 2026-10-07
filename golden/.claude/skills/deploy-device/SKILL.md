---
name: deploy-device
description: Build, install, and launch an Android app on a connected device or emulator with adb. Use when the user wants the app deployed and opened on hardware.
argument-hint: "[app-id] [variant] [adb-serial]"
disable-model-invocation: true
allowed-tools: Read, Grep, Glob, Bash(./gradlew *), Bash(gradlew.bat *), Bash(adb *)
---

# Deploy Device

Build the requested variant of an Android app, install it with `adb`, and launch it.

## Request

$ARGUMENTS

## Inputs

- App: one of the workspace's Android apps. Without `[app-id]`, ask which one when there is more than one.
- Variant: `debug` (default)
- Optional adb serial when multiple devices are connected

## Apps

| App ID | Folder | Application ID |
| --- | --- | --- |
| `mobile-android` | `mobile-android/` | `com.example.prismgolden.mobileandroid` |

## Workflow

1. Resolve the app from `$0` and the variant from `$1` (default `debug`).
2. List devices with `adb devices -l`.
3. Stop if there is no authorized device or emulator.
4. Let the device reach the local backend: run `task <app-id>:reverse` (it forwards the port of the backend the app was generated for, `BACKEND_PORT` in the app's Taskfile; another port is `task <app-id>:reverse BACKEND_PORT=<port>`). The app calls `localhost`, because the backend's local development identity accepts loopback requests only. Do not point the app at `10.0.2.2` or a LAN address.
5. Build the variant from the app's folder:
   - `./gradlew assembleDebug` (or `gradlew.bat` on Windows)
6. Use the APK at `<app folder>/app/build/outputs/apk/debug/app-debug.apk`.
7. Install with `adb install -r`.
8. Launch with `adb shell monkey -p <application id> -c android.intent.category.LAUNCHER 1`.

## Notes

- If multiple devices or emulators are connected and no serial is provided, ask which target to use before install and launch.
- Add `-s <serial>` to adb commands when a target device is specified, including `adb reverse`.
- The sign-in needs the backend running under its `local` profile; the app reports it when the backend is missing or unreachable.
