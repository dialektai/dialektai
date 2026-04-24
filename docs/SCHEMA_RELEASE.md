# Releasing `dialekt-manifest-validator`

The schema package develops independently from the dialekt main repo.
**Distribution is via GitHub tags, not PyPI.** This keeps publishing
friction near zero while we're iterating (no PyPI API token, no waiting
period, no name-squatting risk), and migrating later is a one-line
change in `requirements.txt`.

## Repository

| | |
|---|---|
| Source  | <https://github.com/dialektai/dialekt-manifest-validator> |
| Local   | `/home/dias/projects/python/dialekt-manifest-validator` |
| License | Apache-2.0 |
| Consumed by | `python/requirements.txt` in the main dialekt repo |

## When to bump which part of the version

| Change | Bump | Example |
|---|---|---|
| Add value to an enum (e.g. new autonomy level) | **minor** | `0.2.0 → 0.3.0` |
| Add a new optional field | **minor** | `0.2.0 → 0.3.0` |
| Add a new capability group | **minor** | `0.2.0 → 0.3.0` |
| Bug fix in validation (no schema change) | **patch** | `0.2.0 → 0.2.1` |
| Tighten an existing rule / reject something we used to accept | **major** | `0.2.0 → 1.0.0` |
| Rename / remove a field | **major** | `0.2.0 → 1.0.0` |

When in doubt, ship as minor and add tests.

## Release procedure

### 1 · Prepare

```bash
cd /home/dias/projects/python/dialekt-manifest-validator
git status    # must be clean
git pull      # ensure main is up to date
```

### 2 · Bump the version

Edit `pyproject.toml`:

```toml
version = "0.X.Y"
```

If `src/dialekt_manifest/__init__.py` exposes `__version__`, update it
too (currently it does not — skip this step if absent).

### 3 · Update CHANGELOG

Add an entry at the top of `CHANGELOG.md`:

```markdown
## [0.X.Y] — YYYY-MM-DD

### Added
- …

### Changed
- …

### Fixed
- …
```

### 4 · Commit + tag + push

```bash
git add pyproject.toml CHANGELOG.md
git commit -m "chore(release): 0.X.Y — <one-liner>"
git tag -a v0.X.Y -m "Release 0.X.Y"
git push origin main
git push origin v0.X.Y
```

Verify the tag shows up at
<https://github.com/dialektai/dialekt-manifest-validator/tags>.

### 5 · Clean-room install test

Do this before touching the dialekt repo — catches packaging mistakes
(missing `src/` layout, bad `pyproject.toml`, etc.) early:

```bash
cd /tmp
python3 -m venv tag-test && source tag-test/bin/activate
pip install "git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.X.Y"
python -c "
from dialekt_manifest.schema import AUTONOMY_LEVELS
print('autonomy levels:', AUTONOMY_LEVELS)
"
deactivate && rm -rf /tmp/tag-test
```

### 6 · Update dialekt `requirements.txt`

```bash
cd ~/projects/desktop/dialekt
```

Update the pin in `python/requirements.txt`:

```diff
-dialekt-manifest-validator @ git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.X-1.Y
+dialekt-manifest-validator @ git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.X.Y
```

### 7 · Local verify

```bash
cd python
source venv/bin/activate
pip install -r requirements.txt --upgrade
pytest --ignore=tests/integration -q
```

Expected: all ~302 unit tests pass (integration tests need live DBs
and are skipped by default).

### 8 · Commit + push + watch CI

```bash
git add python/requirements.txt
git commit -m "deps(schema): bump to v0.X.Y — <reason>"
git push
```

Watch the runs: <https://github.com/dialektai/dialektai/actions>.
Both **CI** (unit + frontend) and **E2E Integration** must turn green.

### 9 · Live servers — reload the schema

Running dialekt servers cache the old schema in RAM. Pilots and anyone
on an already-installed build must reload:

- **UI:** Settings → Admin → Maintenance → **Reload validation schema**
- **API:** `curl -X POST http://localhost:8765/admin/reload-schema`

See `docs/UPGRADE.md` for the full reload-vs-restart tradeoffs.

## Future migration to PyPI

When external usage justifies it (e.g. third-party agent authors want
to validate manifests offline):

1. Register the project on PyPI and obtain an API token.
2. Build + upload from the schema repo:
   ```bash
   pip install --upgrade build twine
   python -m build
   python -m twine upload dist/*
   ```
3. Flip `python/requirements.txt` back to a plain pin:
   ```diff
   -dialekt-manifest-validator @ git+https://github.com/dialektai/dialekt-manifest-validator.git@v0.X.Y
   +dialekt-manifest-validator==0.X.Y
   ```
4. Commit + push. CI continues working — pip now resolves from PyPI.

No code changes in the main dialekt repo are needed.

## Troubleshooting

### CI fails with `Could not find a version that satisfies the requirement`

- Confirm the repo is **public**: `gh repo view dialektai/dialekt-manifest-validator --json visibility`
- Confirm the tag exists on GitHub: `git ls-remote --tags https://github.com/dialektai/dialekt-manifest-validator`
- Check the `@v0.X.Y` suffix has the `v` prefix — `@0.X.Y` (no `v`) will 404.

### Local install succeeds but Python import fails

- Check `src/dialekt_manifest/__init__.py` exists in the tagged commit.
- Check `pyproject.toml` has `[tool.setuptools.packages.find]` pointing at `src/`, or an explicit `packages = [...]` list.

### Server keeps rejecting manifests with old enum values after upgrade

- The server cached the old schema. Click **Reload validation schema**
  in Settings → Admin, or `curl -X POST .../admin/reload-schema`.
- If that doesn't help, `pip show dialekt-manifest-validator` — the
  on-disk version may be old too (upgrade + reload).
