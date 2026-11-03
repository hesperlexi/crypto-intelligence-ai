#!/usr/bin/env bash
# Off-cache backup of the engine state (candles, trained models, bot books) as an encrypted GitHub release asset.
#   scripts/engine_backup.sh save      # upload backend/data (three rotating copies, one per 6-hour slot)
#   scripts/engine_backup.sh restore   # when the Actions cache is gone: download the newest copy that decrypts
#   scripts/engine_backup.sh ensure    # save only if the newest copy is missing or older than ENSURE_MAX_AGE_S (6 h)
# The repository is public, so the archive is AES-256 encrypted. Key: the ENGINE_BACKUP_KEY secret when it is set
# (so rotating the Firebase key never breaks the backups), else SHA-256 of FIREBASE_SERVICE_ACCOUNT (the old key).
# Restore tries both keys. Nobody without those secrets can read it. Needs GH_TOKEN and gh. Never prints a key.
# Exit codes of restore: 0 restored, 2 no backup found, 1 a backup exists but could not be restored.
set -euo pipefail
MODE="${1:?save|restore|ensure}"
TAG="engine-backup"
DATA="backend/data"
SLOTS=3                                   # copies kept (each ~1.8 GB, stored in 1.5 GB parts)
ENSURE_MAX_AGE_S="${ENSURE_MAX_AGE_S:-21600}"

KEYS=()
if [ -n "${ENGINE_BACKUP_KEY:-}" ]; then
  KEYS+=("$(printf %s "$ENGINE_BACKUP_KEY" | sha256sum | cut -d' ' -f1)")
fi
if [ -n "${FIREBASE_SERVICE_ACCOUNT:-}" ]; then
  KEYS+=("$(printf %s "$FIREBASE_SERVICE_ACCOUNT" | sha256sum | cut -d' ' -f1)")
fi
if [ "${#KEYS[@]}" -eq 0 ]; then
  echo "::warning::no ENGINE_BACKUP_KEY or FIREBASE_SERVICE_ACCOUNT: backup $MODE skipped"
  [ "$MODE" = restore ] && exit 1
  exit 0
fi
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

if [ "$MODE" = ensure ]; then
  last=$(gh release view "$TAG" --json assets -q '[.assets[] | select(.name | startswith("engine-state-")) | .updatedAt] | max // ""' 2>/dev/null || true)
  if [ -n "$last" ] && [ $(( $(date -u +%s) - $(date -u -d "$last" +%s) )) -lt "$ENSURE_MAX_AGE_S" ]; then echo "backup is fresh ($last)"; exit 0; fi
  MODE=save
fi

if [ "$MODE" = save ]; then
  [ -d "$DATA" ] && [ -n "$(ls -A "$DATA" 2>/dev/null)" ] || { echo "nothing to back up"; exit 0; }
  # one slot per 6-hour period, rotating: a bad backup never replaces the other (older) good copies
  slot=$(( ($(date -u +%s) / 21600) % SLOTS ))
  name="engine-state-${slot}.tar.gz.enc"
  # the first key is the one used for new backups (ENGINE_BACKUP_KEY when set)
  tar -czf - -C backend data | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass "pass:${KEYS[0]}" -out "$TMP/$name"
  gh release view "$TAG" >/dev/null 2>&1 || gh release create "$TAG" --title "Engine backup (encrypted)" \
      --notes "Encrypted engine state, restored automatically when the Actions cache is gone. Not a download." --prerelease
  # a release file may be at most 2 GiB and the state is ~1.8 GB, so it is stored in 1.5 GB parts
  (cd "$TMP" && split -b 1500m -d -a 2 "$name" "${name}.part")
  rm -f "$TMP/$name"
  # remove this slot's older copy (whole file or parts) before uploading the new parts
  for old in $(gh release view "$TAG" --json assets -q '.assets[].name' 2>/dev/null | grep "^engine-state-${slot}\." || true); do
    gh release delete-asset "$TAG" "$old" -y || true
  done
  # copies from slots that no longer exist (e.g. after SLOTS was lowered) are removed too
  for old in $(gh release view "$TAG" --json assets -q '.assets[].name' 2>/dev/null | grep '^engine-state-' || true); do
    s=$(printf %s "$old" | sed -E 's/^engine-state-([0-9]+)\..*/\1/')
    [ "$s" -lt "$SLOTS" ] 2>/dev/null || gh release delete-asset "$TAG" "$old" -y || true
  done
  gh release upload "$TAG" "$TMP"/"${name}".part* --clobber
  echo "backed up $(du -ch "$TMP"/"${name}".part* | tail -1 | cut -f1) to release $TAG as ${name}.part*"
elif [ "$MODE" = restore ]; then
  # newest first; one entry per copy (parts merged)
  copies=$(gh release view "$TAG" --json assets -q '.assets | sort_by(.updatedAt) | reverse | .[].name' 2>/dev/null \
           | grep '^engine-state-' | sed -E 's/\.part[0-9]+$//' | awk '!seen[$0]++' || true)
  [ -n "$copies" ] || { echo "::warning::no engine backup found"; exit 2; }
  mkdir -p backend
  for newest in $copies; do
    rm -rf "$TMP/dl" && mkdir -p "$TMP/dl"
    if ! gh release download "$TAG" -p "${newest}*" -D "$TMP/dl"; then echo "::warning::download of $newest failed"; continue; fi
    if ls "$TMP/dl/${newest}".part* >/dev/null 2>&1; then cat "$TMP/dl/${newest}".part* > "$TMP/dl/$newest"; rm -f "$TMP/dl/${newest}".part*; fi
    i=0
    for k in "${KEYS[@]}"; do
      i=$((i + 1))
      rm -rf backend/.restore && mkdir -p backend/.restore
      if openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass "pass:$k" -in "$TMP/dl/$newest" 2>/dev/null \
           | tar -xzf - -C backend/.restore 2>/dev/null && [ -d backend/.restore/data ]; then
        rm -rf "$DATA" && mv backend/.restore/data "$DATA" && rm -rf backend/.restore
        echo "::notice::engine state restored from backup $newest (key $i of ${#KEYS[@]})"
        exit 0
      fi
    done
    rm -rf backend/.restore "$TMP/dl"
    echo "::warning::backup $newest could not be decrypted with the available keys; trying an older copy"
  done
  echo "::error::no engine backup could be restored"
  exit 1
fi
