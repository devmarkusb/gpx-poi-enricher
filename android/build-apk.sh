#!/bin/bash
# One-shot script: set up Android SDK (first run only) and build a debug APK.
# Output: app/build/outputs/apk/debug/app-debug.apk
#
# Requirements: JDK 17+ (sudo apt install openjdk-17-jdk)
# SDK: defaults to ~/dev/externlibs/Android/Sdk (override with ANDROID_SDK_ROOT).

set -euo pipefail
cd "$(dirname "$0")"

# ── Java 17+ required by Android SDK tools ───────────────────────────────────
if [ -z "${JAVA_HOME:-}" ] || ! "$JAVA_HOME/bin/java" -version 2>&1 | grep -qE 'version "([2-9][0-9]|1[7-9])'; then
    if command -v /usr/libexec/java_home &>/dev/null; then
        JAVA_HOME="$(/usr/libexec/java_home 2>/dev/null)" && export JAVA_HOME
    fi
    for candidate in \
        /opt/homebrew/opt/openjdk@21 /opt/homebrew/opt/openjdk@17 \
        /usr/lib/jvm/java-21-openjdk-amd64 /usr/lib/jvm/java-17-openjdk-amd64; do
        if [ -x "$candidate/bin/java" ]; then
            export JAVA_HOME="$candidate"
            break
        fi
    done
fi
if [ -z "${JAVA_HOME:-}" ]; then
    echo "ERROR: Could not find Java 17+. Install JDK 17 or later." >&2
    exit 1
fi
export PATH="${JAVA_HOME}/bin:$PATH"

# ── Python 3.12 required by Chaquopy (pip bundled with Chaquopy uses 'cgi', removed in 3.13+) ──
if [ "$(uname -s)" = "Darwin" ] && ! command -v python3.12 &>/dev/null; then
    echo ">>> Installing Python 3.12 (needed for Chaquopy build)..."
    brew install python@3.12
    brew link python@3.12
fi

ANDROID_SDK_ROOT="${ANDROID_SDK_ROOT:-$HOME/dev/externlibs/Android/Sdk}"
CMDLINE_TOOLS="$ANDROID_SDK_ROOT/cmdline-tools/latest"
GRADLE_WRAPPER_JAR="gradle/wrapper/gradle-wrapper.jar"

# ── 1. Android command-line tools ────────────────────────────────────────────
if [ ! -f "$CMDLINE_TOOLS/bin/sdkmanager" ]; then
    echo ">>> Downloading Android command-line tools..."
    mkdir -p "$ANDROID_SDK_ROOT/cmdline-tools"
    TMP=$(mktemp -d)
    case "$(uname -s)" in
        Darwin) CMDTOOLS_PLATFORM="mac" ;;
        *)      CMDTOOLS_PLATFORM="linux" ;;
    esac
    curl -fsSL "https://dl.google.com/android/repository/commandlinetools-${CMDTOOLS_PLATFORM}-11076708_latest.zip" \
        -o "$TMP/cmdtools.zip"
    unzip -q "$TMP/cmdtools.zip" -d "$TMP"
    mv "$TMP/cmdline-tools" "$CMDLINE_TOOLS"
    rm -rf "$TMP"
    echo ">>> Command-line tools installed."
fi

export ANDROID_HOME="$ANDROID_SDK_ROOT"
export PATH="$CMDLINE_TOOLS/bin:$ANDROID_HOME/platform-tools:$PATH"

# ── 2. Android SDK platform + build tools ────────────────────────────────────
if [ ! -d "$ANDROID_HOME/platforms/android-34" ]; then
    echo ">>> Installing Android SDK platform 34 and build tools..."
    yes | sdkmanager --licenses > /dev/null 2>&1 || true
    sdkmanager "platforms;android-34" "build-tools;34.0.0"
fi

# ── 3. Gradle wrapper jar ─────────────────────────────────────────────────────
if [ ! -f "$GRADLE_WRAPPER_JAR" ]; then
    echo ">>> Downloading Gradle wrapper jar..."
    curl -fsSL \
        "https://raw.githubusercontent.com/gradle/gradle/v8.7.0/gradle/wrapper/gradle-wrapper.jar" \
        -o "$GRADLE_WRAPPER_JAR"
fi

# ── 4. Build ──────────────────────────────────────────────────────────────────
echo ">>> Building debug APK (first run downloads Gradle + Chaquopy — can take 10–20 min)..."
./gradlew assembleDebug

APK="app/build/outputs/apk/debug/app-debug.apk"
echo ""
echo "✓ Done: $APK  ($(du -h "$APK" | cut -f1))"
