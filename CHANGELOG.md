# Changes

## 0.2.0 (not released yet)

- **The CLOVE island is now Clove Notch**, everywhere you see or type it: the app and its settings, the commands
  `clove-notch` and `clove-notch-hook`, the `notch/` folder, and the folders in `~/.config` and `~/.local/share`.
  On first start it moves the old folders and saved keys across, and hooks set up before the rename keep working.
- The phone link uses upstream's pairing link (`coucou://pair`) and relay key label again, which the phone app
  expects; 0.1.0 had renamed them by mistake. Not yet tried with a phone.

## 0.1.0 (early access)

The first packaged release of CLOVE: the assistant and Clove Notch in one repository.

- **Assistant**: three brains (Gemini Live, Hybrid, local Qwen), wake word, approvals enforced in code, dictation,
  screen reading, web control in Chrome, machines over SSH, coding agents with fallback, routines and day memory.
- **The CLOVE window**: Conversation, Activity, Systems and Preferences, in Clove Notch's look; shown inside
  Clove Notch's window when it is installed.
- **Clove Notch**: rebranded fork of Coucou with CLOVE's own mark, icon and sounds; CLOVE's own pill with Allow /
  Deny; chat with CLOVE; stays on screen; Assistant pages.
- **Starts with your session**: a systemd user service, and Clove Notch's login item.
- **Installer** (`install.sh`) for a fresh PC.
- **Desktop support**: window control and package installs for Hyprland and pacman, apt, dnf and zypper; the
  prompt describes the real OS and desktop instead of assuming one.
