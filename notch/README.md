# Clove Notch

The bar at the top of the screen, and the CLOVE app's window. It shows what CLOVE and your coding agents (Claude
Code, Codex, Gemini CLI and others) are doing, with **Allow / Deny** for anything waiting for approval, and holds
the CLOVE window's pages (Assistant), dictation and the Notetaker (Flow), and Clove Notch's own settings (Notch).

It is a fork of [Coucou](https://github.com/Louis-CFM/coucou) by Louis Raillé (MIT, see `LICENSE`), rebranded
as CLOVE with its own mark, icon and sounds, and connected to the CLOVE assistant. `CLOVE-FORK.md` lists every
change.

**Tested on**: Arch Linux (Omarchy) with Hyprland on Wayland. Upstream also targets Windows; this fork has not been
tested there.

## Build and install

Needs Rust (cargo) and Node.js (npm). From this folder:

```bash
npm install
npx tauri build --no-bundle
install -m755 target/release/clove-notch ~/.local/bin/clove-notch
install -m755 target/release/clove-notch-hook ~/.local/bin/clove-notch-hook
clove-notch
```

The top-level `install.sh` does the same. Clove Notch starts at login once "Open at login" is on in General
(it is, by default).

## Tests

```bash
npm test             # the interface (node --test)
npx tsc --noEmit     # types
cd src-tauri && cargo test --release --lib
```

## Connected to CLOVE

- **Assistant pages**: the CLOVE window, read from the address CLOVE writes at start (`$XDG_RUNTIME_DIR/clove.url`).
  If CLOVE isn't running, the page says so and can start its service.
- **Chat**: Clove Notch's chat asks CLOVE itself, over CLOVE's control socket.
- **CLOVE's pill**: CLOVE reports its requests, tool steps, replies and plans; a plan waiting for approval comes
  up with Allow / Deny.
