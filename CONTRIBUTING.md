# Contributing to dialekt

Thanks for your interest in contributing. Here's everything you need to know.

---

## Developer Certificate of Origin (DCO)

All commits must be signed off. By signing off, you certify that you wrote the code and have the right to submit it under the project's license.

Add `-s` to your commit command:

```sh
git commit -s -m "feat: add support for custom model paths"
```

This appends a `Signed-off-by: Your Name <your@email.com>` line to the commit message. Without it, the PR will not be merged.

Full DCO text: https://developercertificate.org

---

## Getting Started

1. Fork the repo and clone your fork
2. Set up the dev environment (see README.md)
3. Create a feature branch: `git checkout -b feat/your-feature`
4. Make changes, write/update tests if applicable
5. Run tests: `cd python && pytest tests/`
6. Commit with sign-off: `git commit -s`
7. Push and open a PR against `main`

---

## Code Style

- **Python**: follow PEP 8, keep functions small
- **React/JS**: functional components, no class components
- **Rust**: `cargo fmt` before committing
- No AI-generated boilerplate — every line should have a reason

---

## What to Contribute

Good first issues are labeled `good-first-issue` on GitHub.

High-value contributions:
- New Ollama model presets
- Improved autonomy mode controls
- Better error handling in the Python backend
- UI improvements in `frontend/src/`
- Additional OS-level actions (clipboard, screenshots, notifications)
- Windows testing and fixes

---

## What NOT to Submit

- PRs that add external cloud API dependencies (this is a local-first app)
- New dependencies without a discussion issue first
- Auto-generated or vibe-coded files with no clear purpose

---

## Licensing Note

By contributing to dialekt, you agree that your contributions will be licensed under the GNU Affero General Public License v3.0. If the project ever offers a commercial license to third parties, DCO-signed contributions may be included — the DCO itself confirms you have the right to license your code this way.
