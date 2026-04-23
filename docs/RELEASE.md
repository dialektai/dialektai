# dialekt Release Procedure

## Prerequisites (one-time setup)

### Secrets to configure in GitHub repo settings
Go to `github.com/dialektai/dialektai` → Settings → Secrets and variables → Actions:

| Secret | Description |
|--------|-------------|
| `TAURI_SIGNING_PRIVATE_KEY` | Tauri updater private key (generated with `npm run tauri signer generate`) |
| `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` | Password for updater key |
| `APPLE_CERTIFICATE` | Base64-encoded `.p12` file (Apple Developer ID Application certificate) |
| `APPLE_CERTIFICATE_PASSWORD` | Password for `.p12` file |
| `APPLE_SIGNING_IDENTITY` | e.g. `Developer ID Application: Your Name (TEAMID)` |
| `APPLE_ID` | Your Apple ID email |
| `APPLE_APP_SPECIFIC_PASSWORD` | App-specific password for notarization |
| `APPLE_TEAM_ID` | 10-char Apple Team ID |
| `KEYCHAIN_PASSWORD` | Any random string (used internally in CI keychain) |

Until you have the Apple Developer Program ($99/year), the macOS build will be
**unsigned**. It still works with the Gatekeeper workaround (see below).

### Generate Tauri updater key (one-time)
```bash
cd frontend
npm run tauri signer generate -- --output updater.key
# Save the public key to tauri.conf.json under plugins.updater.pubkey
# Save the private key as TAURI_SIGNING_PRIVATE_KEY secret (base64-encoded)
```

---

## Standard release process

### Step 1 — Update version number in three places

```bash
# frontend/src-tauri/tauri.conf.json
"version": "0.9.0"

# frontend/package.json
"version": "0.9.0"

# python/server.py (or dialekt_server.spec if present)
VERSION = "0.9.0"
```

Or use the helper:
```bash
./scripts/bump_version.sh 0.9.0
```

### Step 2 — Update CHANGELOG (optional but recommended)

Add a section to `CHANGELOG.md`:
```markdown
## [0.9.0] - 2026-05-15
### Added
- Onboarding flow wired end-to-end
- Ollama install detection and guided setup
...
```

### Step 3 — Run full test suite locally

```bash
cd python
source venv/bin/activate
python -m pytest -q
```

All tests must pass before tagging.

### Step 4 — Tag and push

```bash
git tag v0.9.0
git push origin v0.9.0
```

This triggers the GitHub Actions release workflow automatically.

### Step 5 — Monitor the build

Go to `github.com/dialektai/dialektai` → Actions → Release.

Build times:
- macOS: ~15-20 min (universal binary + PyInstaller)
- Linux: ~10 min
- Windows: ~12 min

### Step 6 — Verify the release

1. Check GitHub Releases page — all three platform artifacts should be attached
2. Download the macOS `.dmg` on a test machine
3. Install and verify the app opens + backend starts
4. Confirm version number in dialekt → About

---

## macOS Gatekeeper workaround (unsigned builds)

Until Apple Developer signing is active, share this with users:

```bash
# After dragging dialekt to /Applications:
xattr -cr /Applications/dialekt.app

# Or right-click → Open → Open (bypasses Gatekeeper once)
```

Add this to user-facing README and to the GitHub Release notes (the CI workflow
does this automatically).

---

## Hotfix release

For urgent bug fixes:

```bash
git checkout -b hotfix/0.8.3
# make fix
git commit -s -m "fix: ..."
git tag v0.8.3
git push origin hotfix/0.8.3 v0.8.3
```

---

## Cloud service deploy (dialekt-cloud)

After releasing the desktop app, update the cloud service if needed:

```bash
ssh dias@server
cd /home/dias/projects/desktop/dialekt-cloud
git pull
docker compose pull
docker compose up -d --build
```

Verify: `curl https://api.dialekt.ai/health`

---

## Rollback

If a release has a critical bug:

1. Delete the GitHub Release (mark as pre-release or delete entirely)
2. Fix the bug on a hotfix branch
3. Tag a new patch version
4. In `dialekt-cloud`, the `updater.json` can be reverted to point to previous version

---

## Release checklist

- [ ] Version bumped in tauri.conf.json, package.json
- [ ] `python -m pytest -q` passes (192+ tests)
- [ ] `npm run build` in frontend passes
- [ ] Tag created and pushed
- [ ] GitHub Actions release completed
- [ ] macOS `.dmg` downloaded and verified
- [ ] GitHub Release notes contain Gatekeeper workaround
- [ ] Cloud service health check passes
- [ ] MEMORY.md / dialekt.md updated with new version
