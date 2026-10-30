# Plan: one copy of CLOVE on this PC

**Why.** The CLOVE that runs at login comes from two older folders, not from this repository:
- the assistant: `/run/media/ak/Drive/clove` (the `clove.service` user service);
- Clove Notch: built from `~/Projects/clove-island/windows` and installed to `~/.local/bin`.

Every fix has to be made twice, and the copies have already drifted (personal routines and defaults live only in
the old folder).

**What.**
1. After "Rename the island to Clove Notch" is merged: build and install `clove-notch` from `notch/`, and check that
   the first start moves `~/.config/clove-island` and `~/.local/share/clove-island`, keeps the Claude Code status
   line and hooks working, and keeps WhatsApp linked.
2. Point `clove.service` and the app-grid entry at `assistant/` in this repository (personal settings stay in its
   `.env`, which git ignores).
3. Move personal routines to `assistant/routines/local/` (ignored by git).
4. Archive the two old folders (rename, don't delete) once a week of normal use has passed.

**Done when.** After a reboot CLOVE and Clove Notch start from this repository, "Clove, what time is it?" is
answered, and the old folders are no longer used by anything (`lsof`, the service file and the desktop entries).

## Progress

- [x] Personal routines load from `assistant/routines/local/` (git ignores it); the three are copied there.
- [x] `assistant/.venv` copied from the old folder (same packages); `notch/` built from this repository.
- [x] Clove Notch's settings and WebKit data are already under the new names, with links at the old paths.
- [x] `assistant/.env` copied from the old folder (by the owner: it holds the keys).
- [x] Switched over (30 Oct): `clove-notch` installed, desktop entries and icons renamed, `clove.service` and the
      `clove` command point here. The first start moved the data folder and left links at the old paths. CLOVE
      answered a typed question; the Claude Code status line runs; WhatsApp's gateway kept its link.
- [ ] Re-add the Chrome extension from `assistant/chrome_extension` (it still loads from the old folder).
- [ ] After a reboot: both start on their own.
- [ ] Archive the old folders after a week.
