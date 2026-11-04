#!/usr/bin/env bash
# Packages the app with electron-builder for a release (used by
# .github/workflows/release.yml). Arguments are passed to electron-builder,
# e.g. `bash scripts/package-release.sh --mac --arm64`.
#
# Explicit --platform --arch flags make electron-builder ignore the arch
# arrays in electron-builder.yml and only build what this runner can produce.
# PyInstaller binaries are platform-specific, so cross-compiling is not possible.
#
# macOS: sign and notarize with the MACOS_* secrets (docs/macos-signing.md).
# They are exported only on macOS, or electron-builder would use CSC_LINK on
# Windows.
set -eo pipefail

if [ "$RUNNER_OS" = "macOS" ]; then
  for name in MACOS_CERTIFICATE_P12_BASE64 MACOS_CERTIFICATE_PASSWORD \
      MACOS_NOTARY_API_KEY_P8 MACOS_NOTARY_API_KEY_ID MACOS_NOTARY_API_ISSUER_ID; do
    if [ -z "${!name}" ]; then
      echo "::error::Secret $name is not set (see docs/macos-signing.md)"
      exit 1
    fi
  done
  export CSC_LINK="$MACOS_CERTIFICATE_P12_BASE64"
  export CSC_KEY_PASSWORD="$MACOS_CERTIFICATE_PASSWORD"
  # notarytool needs the API key as a file.
  export APPLE_API_KEY="$RUNNER_TEMP/AuthKey.p8"
  printf '%s\n' "$MACOS_NOTARY_API_KEY_P8" > "$APPLE_API_KEY"
  trap 'rm -f "$APPLE_API_KEY"' EXIT
  export APPLE_API_KEY_ID="$MACOS_NOTARY_API_KEY_ID"
  export APPLE_API_ISSUER="$MACOS_NOTARY_API_ISSUER_ID"
fi
unset MACOS_CERTIFICATE_P12_BASE64 MACOS_CERTIFICATE_PASSWORD MACOS_NOTARY_API_KEY_P8

# --publish never: with GH_TOKEN set on a tag build, electron-builder would
# otherwise auto-publish its artifacts (incl. blockmaps and latest*.yml) to
# the GitHub Release, bypassing the filtered upload step in release.yml.
#
# Retried a few times: even with Spotlight off, the DMG step can still hit a
# transient hdiutil race on a loaded runner.
n=0
until npx electron-builder "$@" --publish never; do
  n=$((n + 1))
  if [ "$n" -ge 3 ]; then
    echo "electron-builder failed after $n attempts"
    exit 1
  fi
  echo "electron-builder failed (attempt $n/3) — force-detaching any stuck disk images, retrying in 10s..."
  if [ "$(uname -s)" = "Darwin" ]; then
    hdiutil info | awk '/^\/dev\/disk/ {print $1}' | xargs -I{} hdiutil detach -force {} 2>/dev/null || true
  fi
  sleep 10
done
