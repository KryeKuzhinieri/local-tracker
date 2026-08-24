#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

sensitive_path_pattern='(^|/)(data\.json|data\.backup\.json|data-[0-9T.Z-]+\.json|tracker-data|user-data|local-tracker-backups)(/|$)'
tracked_paths="$(git log --all --pretty=format: --name-only | sort -u)"

if printf '%s\n' "$tracked_paths" | rg "$sensitive_path_pattern"; then
  echo "Blocked: personal tracking data exists in Git history." >&2
  exit 1
fi

while IFS= read -r object; do
  hash="${object%% *}"
  path="${object#* }"
  case "$path" in
    *.json)
      content="$(git show "$hash" 2>/dev/null || true)"
      if printf '%s' "$content" | rg -q '"schema_version"' \
        && printf '%s' "$content" | rg -q '"entries"' \
        && printf '%s' "$content" | rg -q '"projects"'; then
        echo "Blocked: serialized tracking data found in $path." >&2
        exit 1
      fi
      ;;
  esac
done < <(git rev-list --objects --all)

echo "No personal tracking data found in Git."
