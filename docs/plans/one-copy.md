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
