# Plan: ready-made builds, no compiler needed

**Why.** Today `./install.sh` builds Clove Notch from source: Rust and Node.js must be installed, and the first
build takes about ten minutes. For someone non-technical, or a buyer of the template, that is the step where they
give up.

**What.**
- A release workflow that, on a version tag, builds `clove-notch` and `clove-notch-hook` for x86-64 Linux and
  attaches them (and an AppImage) to a GitHub release, with checksums.
- `install.sh` downloads the matching release when one exists and only builds from source when asked
  (`--from-source`), checking the checksum first.
- A `CHANGELOG.md` entry per release; the version in one place.

**Done when.** On a fresh Ubuntu and a fresh Arch install without Rust or Node.js, `./install.sh` finishes in under
three minutes and Clove Notch starts.
