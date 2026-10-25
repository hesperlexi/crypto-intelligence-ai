#!/usr/bin/env bash
# Off-cache backup of the engine state (candles, trained models, bot books) as an encrypted GitHub release asset.
#   scripts/engine_backup.sh save      # after training: upload backend/data (two rotating copies)
#   scripts/engine_backup.sh restore   # when the Actions cache is gone: download the newest copy
#   scripts/engine_backup.sh ensure    # save only if the newest copy is missing or older than 26 hours
# The repository is public, so the archive is AES-256 encrypted with a key derived from the
# FIREBASE_SERVICE_ACCOUNT secret; nobody without that secret can read it. Needs GH_TOKEN and gh.
set -euo pipefail
MODE="${1:?save|restore}"
TAG="engine-backup"
DATA="backend/data"
[ -n "${FIREBASE_SERVICE_ACCOUNT:-}" ] || { echo "::warning::no FIREBASE_SERVICE_ACCOUNT: backup skipped"; exit 0; }
KEY="$(printf %s "$FIREBASE_SERVICE_ACCOUNT" | sha256sum | cut -d' ' -f1)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ "$MODE" = ensure ]; then
  last=$(gh release view "$TAG" --json assets -q '[.assets[] | select(.name | startswith("engine-state-")) | .updatedAt] | max // ""' 2>/dev/null || true)
  if [ -n "$last" ] && [ $(( $(date -u +%s) - $(date -u -d "$last" +%s) )) -lt 93600 ]; then echo "backup is fresh ($last)"; exit 0; fi
  MODE=save
fi

if [ "$MODE" = save ]; then
  [ -d "$DATA" ] && [ -n "$(ls -A "$DATA" 2>/dev/null)" ] || { echo "nothing to back up"; exit 0; }
  slot=$(( $(date -u +%j) % 2 ))                     # alternate days: a bad backup never replaces the only good one
  name="engine-state-${slot}.tar.gz.enc"
  tar -czf - -C backend data | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "pass:$KEY" -out "$TMP/$name"
  gh release view "$TAG" >/dev/null 2>&1 || gh release create "$TAG" --title "Engine backup (encrypted)" \
      --notes "Encrypted engine state, restored automatically when the Actions cache is gone. Not a download." --prerelease
  gh release upload "$TAG" "$TMP/$name" --clobber
  echo "backed up $(du -h "$TMP/$name" | cut -f1) to release $TAG as $name"
elif [ "$MODE" = restore ]; then
  newest=$(gh release view "$TAG" --json assets -q '.assets | sort_by(.updatedAt) | reverse | .[].name' 2>/dev/null | grep '^engine-state-' | head -1 || true)
  [ -n "$newest" ] || { echo "::warning::no engine backup found: starting fresh"; exit 0; }
  gh release download "$TAG" -p "$newest" -D "$TMP"
  mkdir -p backend
  openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "pass:$KEY" -in "$TMP/$newest" | tar -xzf - -C backend
  echo "::notice::engine state restored from backup $newest"
fi
