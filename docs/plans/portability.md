# Plan: works beyond Arch with Hyprland

**Why.** CLOVE has been tested on one setup: Arch Linux (Omarchy), Hyprland on Wayland, an NVIDIA GPU. Most buyers
and users will be on Ubuntu or Fedora with GNOME or KDE.

**What.**
- Run the installer and a short checklist (wake word, an app opens, window control, dictation, Clove Notch shows
  and stays on screen, Allow / Deny, start at login) on: Ubuntu 24.04 GNOME, Fedora KDE, and Arch Hyprland.
- Fix what fails; window control already has GNOME, wmctrl and Hyprland backends, KDE needs checking.
- Write the result as a "Tested on" table in the README, so nobody is promised more than works.

**Done when.** The checklist passes on all three, or the README states plainly what doesn't work where.
