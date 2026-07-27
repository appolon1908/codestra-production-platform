#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null)" || {
  echo "Not inside a Git repository." >&2
  exit 1
}
cd "$ROOT"

REPORT_DIR="reports/github"
mkdir -p "$REPORT_DIR"

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
status_report="$REPORT_DIR/PRE_INITIAL_COMMIT_STATUS.md"
inventory="$REPORT_DIR/WORKING_TREE_INVENTORY.csv"
large="$REPORT_DIR/UNTRACKED_LARGE_FILES.csv"
suspicious="$REPORT_DIR/POTENTIALLY_SENSITIVE_PATHS.txt"

{
  printf '# Pre-Initial Commit Status\n\n'
  printf 'Generated UTC: `%s`\n\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  printf '## Repository\n\n```text\n'
  git rev-parse --show-toplevel
  git remote -v || true
  git status --short --branch
  printf '```\n'
} > "$status_report"

printf 'status,path,bytes,file_type,classification\n' > "$inventory"
{
  git ls-files --modified -z |
    while IFS= read -r -d '' path; do
      printf ' M\0%s\0tracked-modified\0' "$path"
    done
  git ls-files --others --exclude-standard -z |
    while IFS= read -r -d '' path; do
      printf '??\0%s\0untracked\0' "$path"
    done
} | while IFS= read -r -d '' status &&
          IFS= read -r -d '' path &&
          IFS= read -r -d '' classification; do
  bytes=""
  file_type=""
  if [[ -f "$path" ]]; then
    bytes="$(wc -c < "$path" | tr -d ' ')"
    file_type="$(file -b -- "$path" 2>/dev/null || printf unknown)"
  elif [[ -L "$path" ]]; then
    file_type="symbolic link"
  fi
  printf '"%s","%s","%s","%s","%s"\n' \
    "$status" "${path//\"/\"\"}" "$bytes" \
    "${file_type//\"/\"\"}" "$classification" >> "$inventory"
done

printf 'path,bytes,file_type\n' > "$large"
git ls-files --others --exclude-standard -z | while IFS= read -r -d '' path; do
  if [[ -f "$path" ]]; then
    bytes="$(wc -c < "$path" | tr -d ' ')"
    if (( bytes >= 1048576 )); then
      file_type="$(file -b -- "$path" 2>/dev/null || printf unknown)"
      printf '"%s","%s","%s"\n' \
        "${path//\"/\"\"}" "$bytes" "${file_type//\"/\"\"}" >> "$large"
    fi
  fi
done

find . -path ./.git -prune -o -type f \( \
  -name '.env' -o -name '.env.*' -o -name '*.pem' -o -name '*.key' \
  -o -name '*.p12' -o -name '*.pfx' -o -name '*.sql' -o -name '*.sql.gz' \
  -o -name '*.dump' -o -name '*.backup' -o -iname '*credential*' \
  -o -iname '*secret*' -o -iname '*token*' -o -iname '*recording*' \
\) -print | sort > "$suspicious"

cat <<EOF
CURATION_INVENTORY_COMPLETE=YES
STATUS_REPORT=$status_report
WORKING_TREE_INVENTORY=$inventory
LARGE_UNTRACKED_REPORT=$large
POTENTIALLY_SENSITIVE_PATHS=$suspicious
NEXT=Review every report. Do not run git add -A until files are classified and secret scanning is complete.
EOF
