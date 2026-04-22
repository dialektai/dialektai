---
name: release
description: Build a production release of dialekt — PyInstaller binary + Tauri bundle
---

## Full release build

```bash
cd /home/dias/projects/desktop/dialekt
bash build.sh
```

This does:
1. Activates Python venv
2. Runs PyInstaller on `python/dialekt_server.spec` → `python/dist/dialekt-server`
3. Copies the binary to `frontend/src-tauri/binaries/dialekt-server-<target-triple>`
4. Runs `npm run tauri build` in `frontend/`

Output: `frontend/src-tauri/target/release/bundle/`

## Before releasing — checklist

- [ ] Version bumped in `frontend/src-tauri/tauri.conf.json` (`version` field)
- [ ] Version matches in `frontend/package.json`
- [ ] `requirements.txt` is up to date
- [ ] Tests pass: `cd python && pytest tests/ -v`
- [ ] No hardcoded paths in `server.py` or `Modelfile.example`
- [ ] Commit and tag: `git tag v0.x.y && git push origin v0.x.y`

## Bump version

```bash
# Edit tauri.conf.json and package.json version fields, then:
git commit -s -am "chore: bump version to v0.x.y"
git tag v0.x.y
git push origin main --tags
```
