#!/usr/bin/env bash
# Bump dialekt's user-visible version in every file that hardcodes it.
#
# Usage:
#   scripts/bump-version.sh 0.27.15
#   scripts/bump-version.sh v0.27.15   # leading "v" tolerated, stripped
#
# Why a script: the version lives in 5 files (Tauri config, Cargo
# manifest+lock, Python sidecar, FE constant) and forgetting any one
# of them produces silent mismatches — historically an /about endpoint
# claiming v0.8.2 while the binary said v0.27.10. One command, one
# truth.

set -euo pipefail

NEW="${1:?usage: $0 <version>}"
NEW="${NEW#v}"

if ! [[ "$NEW" =~ ^[0-9]+\.[0-9]+\.[0-9]+([.-][0-9A-Za-z]+)*$ ]]; then
  echo "error: '$NEW' doesn't look like X.Y.Z" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# macOS sed needs an explicit backup suffix even when in-place; Linux's
# GNU sed accepts -i alone. Use the macOS form (-i.bak) and clean up.
sed_inplace() {
  sed -i.bak "$@"
}

# 1. Tauri config — version field at top level
sed_inplace -E 's/("version":[[:space:]]*")[^"]+(")/\1'"$NEW"'\2/' \
  "$ROOT/frontend/src-tauri/tauri.conf.json"

# 2. Cargo.toml — package version
sed_inplace -E 's/^(version[[:space:]]*=[[:space:]]*")[^"]+(")/\1'"$NEW"'\2/' \
  "$ROOT/frontend/src-tauri/Cargo.toml"

# 3. Cargo.lock — only the dialekt entry. sed across "name=...\nversion="
#    is fragile across BSD/GNU; Python regex is simpler and portable.
python3 - "$NEW" "$ROOT/frontend/src-tauri/Cargo.lock" <<'PY'
import re, sys
new, path = sys.argv[1], sys.argv[2]
src = open(path).read()
new_src, n = re.subn(
    r'(name = "dialekt"\nversion = ")[^"]+(")',
    lambda m: m.group(1) + new + m.group(2),
    src, count=1,
)
if n != 1:
    sys.exit(f"error: dialekt entry not found exactly once in Cargo.lock (matched {n} times)")
open(path, "w").write(new_src)
PY

# 4. Python sidecar — DIALEKT_VERSION constant
sed_inplace -E 's/^(DIALEKT_VERSION[[:space:]]*=[[:space:]]*")[^"]+(")/\1'"$NEW"'\2/' \
  "$ROOT/python/server.py"

# 5. Frontend — APP_VERSION constant
sed_inplace -E "s/(APP_VERSION[[:space:]]*=[[:space:]]*')[^']+(')/\\1$NEW\\2/" \
  "$ROOT/frontend/src/version.js"

# Cleanup
find "$ROOT/frontend/src-tauri" "$ROOT/python" "$ROOT/frontend/src" \
  -maxdepth 3 -name "*.bak" -delete 2>/dev/null || true

echo "✓ bumped to $NEW in:"
echo "  frontend/src-tauri/tauri.conf.json"
echo "  frontend/src-tauri/Cargo.toml"
echo "  frontend/src-tauri/Cargo.lock"
echo "  python/server.py"
echo "  frontend/src/version.js"
echo
echo "next:"
echo "  git add -A && git commit -m 'release(v$NEW): ...'"
echo "  git tag v$NEW && git push origin main && git push origin v$NEW"
