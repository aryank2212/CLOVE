# Security

CLOVE can run commands, use your browser and control your machines, so its safety rules matter.

## How CLOVE protects you

- **Risky actions wait for your yes**: installing, deleting, restarting services, sudo, phone calls, and anything
  sent or bought on a website. The check happens in the program (`assistant/tools.py`, `deletion_guard.py`),
  not in the AI's instructions, so a confused or manipulated model can't skip it.
- **No passwords in commands**: CLOVE refuses commands that pipe a password into sudo; sudo passwords are read
  from `assistant/.env` and passed on standard input only.
- **Local only**: the CLOVE window listens on 127.0.0.1 with a new random token each run and checks the page's
  origin; the control socket (`~/.local/state/clove/ctl.sock`) is readable by your user only.
- **Coding agents** run in their own safe modes and edit project files only; system changes come back to CLOVE
  for approval.
- **Your keys** stay in `assistant/.env` (mode 600) and are never sent anywhere except to the service they belong to.

## Reporting a problem

Please don't open a public issue for a security problem. Use GitHub's **Report a vulnerability** (Security tab
of this repository), with what you did, what happened, and the CLOVE version (shown at the bottom of the
window's sidebar). You'll get an answer within a week.
