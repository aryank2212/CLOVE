# Changes

## 0.1.0 (early access)

The first packaged release of CLOVE: the assistant and the CLOVE island in one repository.

- **Assistant**: three brains (Gemini Live, Hybrid, local Qwen), wake word, approvals enforced in code, dictation,
  screen reading, web control in Chrome, machines over SSH, coding agents with fallback, routines and day memory.
- **The CLOVE window**: Conversation, Activity, Systems and Preferences, in the island's look; shown inside the
  island's window when it is installed.
- **The island**: rebranded fork of Coucou with CLOVE's own mark, icon and sounds; CLOVE's own pill with Allow /
  Deny; chat with CLOVE; stays on screen; Assistant pages.
- **Starts with your session**: a systemd user service, and the island's login item.
- **Installer** (`install.sh`) for a fresh PC.
- **Desktop support**: window control and package installs for Hyprland and pacman, apt, dnf and zypper; the
  prompt describes the real OS and desktop instead of assuming one.
