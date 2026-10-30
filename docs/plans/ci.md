# Plan: run every test on each pull request

**Why.** Nothing checks a pull request today: tests run only when someone remembers to run them on their own PC.
With checks on GitHub, a change that breaks something shows a red cross before it is merged.

**What.**
- A GitHub Actions workflow on every pull request and push to `main`:
  - Assistant: Python 3.12, `pip install -r assistant/requirements.txt`, then the tests that need no microphone,
    GPU or Chrome (memory, fastpath, tools guard, call routing, dashboard, notch, new features).
  - Clove Notch: Node 22, `npm ci`, `npx tsc --noEmit`, `npm test`.
  - Clove Notch, Rust: Ubuntu with the WebKitGTK and GTK layer-shell packages, `cargo test --workspace`, with a
    cache so later runs take a few minutes.
- Mark the three as required checks on `main` (repository settings, done by the owner).

**Done when.** A pull request shows three green checks, and a deliberately broken test turns one red.

**Watch for.** Actions minutes on a private repository (2,000 free a month on the free plan; the Rust job is the
expensive one, so it runs only when `notch/` changes). Tests that need audio or a display are skipped on GitHub
and stay in `assistant/tests/run_all.sh` for local runs.
