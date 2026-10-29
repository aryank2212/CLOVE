"""Clove's own hands on every machine: this PC ("local") and any machine in MACHINES (over SSH, e.g. Tailscale).

Clove (Gemini) runs commands, checks health and manages services here directly; coding agents are only for
genuinely complex work (see cli_adapter). Remote commands go through `ssh -o BatchMode=yes`, so they need key
auth (set up once with ssh-copy-id). sudo on a machine reads <NAME>_SUDO_PASSWORD from .env, sent on stdin only.
"""
import re
import shlex
import subprocess

import config
import desktop

# "echo pw | sudo -S ...", "sudo -S <<< pw", "printf pw | sudo": a password typed into the command line
PASSWORD_PIPE = re.compile(r"(?:echo|printf)\s+\S+.*\|\s*sudo\b|\bsudo\s+(?:-\w+\s+)*-S\b|<<<.*\bsudo\b|\bsudo\b.*<<<", re.I)
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "-o", "ServerAliveInterval=15"]
# Non-login SSH shells miss ~/.local/bin and npm globals, where the agent CLIs live.
REMOTE_PATH = 'export PATH="$HOME/.local/bin:$HOME/.npm-global/bin:$HOME/bin:/usr/local/bin:$PATH"; '


def names() -> list[str]:
    return ["local"] + list(config.MACHINES)


def resolve(machine: str) -> str:
    m = (machine or "local").strip().lower()
    if m in ("", "local", "here", "this", "pc", "laptop", "me", config.HOSTNAME.lower()):
        return "local"
    if m in config.MACHINES:
        return m
    raise ValueError(f"unknown machine {machine!r}; known: {', '.join(names())}")


def ssh_argv(machine: str, script: str) -> list[str]:
    return ["ssh", *SSH_OPTS, config.MACHINES[machine], "bash -c " + shlex.quote(REMOTE_PATH + script)]


def _sudo_password(machine: str) -> str:
    return config.SUDO_PASSWORD if machine == "local" else config.MACHINE_SUDO.get(machine, "")


def run(machine: str, command: str, timeout: int = 30, sudo: bool = False, stdin: str | None = None) -> str:
    """Run a shell command on a machine and return 'exit N' plus its output (like desktop.run_command)."""
    if desktop.CATASTROPHIC.search(command):
        return "refused: this command could destroy the system"
    if PASSWORD_PIPE.search(command):
        return ("refused: never put a password in a command (it ends up in logs and process lists). Run the same "
                "command without the password and with sudo=true; Clove supplies the password from .env.")
    try:
        machine = resolve(machine)
    except ValueError as e:
        return f"error: {e}"
    timeout = max(1, min(int(timeout or 30), 600))
    if machine == "local" and not sudo and stdin is None:
        return desktop.run_command(command, timeout)          # the persistent shell (cd/env survive)
    script = command
    if sudo:
        pw = _sudo_password(machine)
        if not pw:
            key = "SUDO_PASSWORD" if machine == "local" else f"{machine.upper()}_SUDO_PASSWORD"
            return f"error: sudo on {machine} needs {key} in .env"
        script = f"sudo -S -p '' bash -c {shlex.quote(command)}"
        stdin = pw + "\n" + (stdin or "")
    argv = ["bash", "-c", script] if machine == "local" else ssh_argv(machine, script)
    try:
        p = subprocess.run(argv, input=stdin, capture_output=True, text=True, timeout=timeout,
                           stdin=None if stdin is not None else subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"timeout after {timeout}s"
    out = ((p.stdout or "") + (("\n" + p.stderr) if p.stderr.strip() else "")).strip()
    if p.returncode == 255 and machine != "local":
        return f"error: can't reach {machine} over SSH ({out[-300:]})"
    return f"exit {p.returncode}\n{out[-4000:]}"


OVERVIEW = r"""
echo "host: $(hostname) | up $(uptime -p | sed 's/^up //') | load $(cut -d' ' -f1-3 /proc/loadavg)"
free -h | awk '/Mem:/{print "memory: "$3" used of "$2", "$7" available"}'
df -h -x tmpfs -x devtmpfs -x squashfs -x overlay -x efivarfs 2>/dev/null | awk 'NR>1 && $2+0>1 {print "disk "$6": "$5" used ("$4" free)"}'
f=$(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | tr '\n' ' '); echo "failed services: ${f:-none}"
if command -v docker >/dev/null && docker info >/dev/null 2>&1; then
  echo "containers: $(docker ps -q | wc -l) running, $(docker ps -aq -f status=exited | wc -l) stopped"
  docker ps -a --format '{{.Names}} {{.Status}}' | grep -Ei 'unhealthy|restarting|exited \([1-9]' | sed 's/^/  problem: /'
fi
echo "busiest: $(ps -eo comm,%cpu --sort=-%cpu --no-headers | head -3 | awk '{printf "%s %s%%, ", $1, $2}')"
"""


def overview(machine: str = "local") -> str:
    """One-glance health: uptime, load, memory, disks, failed services, broken containers, busiest processes."""
    try:
        machine = resolve(machine)
    except ValueError as e:
        return f"error: {e}"
    argv = ["bash", "-c", OVERVIEW] if machine == "local" else ssh_argv(machine, OVERVIEW)
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=40, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"error: {machine} didn't answer in 40 s"
    if p.returncode == 255 and machine != "local":
        return f"error: can't reach {machine} over SSH ({p.stderr.strip()[-200:]})"
    return f"[{machine}]\n" + p.stdout.strip()


SERVICE_ACTIONS = ("status", "logs", "restart", "start", "stop")


def service(machine: str, name: str, action: str = "status", lines: int = 60) -> str:
    """Manage a Docker container or a systemd service by name (Docker is tried first)."""
    if action not in SERVICE_ACTIONS:
        return f"error: action must be one of {', '.join(SERVICE_ACTIONS)}"
    if not name or not all(c.isalnum() or c in "-_.@" for c in name):
        return "error: give a plain service or container name"
    n, lines = shlex.quote(name), max(5, min(int(lines or 60), 400))
    docker = {"status": f"docker ps -a --filter name=^/{name}$ --format '{{{{.Names}}}}: {{{{.Status}}}} ({{{{.Image}}}})'",
              "logs": f"docker logs --tail {lines} {n} 2>&1",
              "restart": f"docker restart {n}", "start": f"docker start {n}", "stop": f"docker stop {n}"}[action]
    unit = {"status": f"systemctl status --no-pager -n 15 {n}", "logs": f"journalctl -u {n} -n {lines} --no-pager",
            "restart": f"systemctl restart {n}", "start": f"systemctl start {n}", "stop": f"systemctl stop {n}"}[action]
    is_container = f"docker inspect {n} >/dev/null 2>&1"
    if action in ("status", "logs"):
        return run(machine, f"if {is_container}; then {docker}; else {unit} 2>&1; fi", 40, stdin="")
    # Changing a systemd unit needs root; try a user unit first, then sudo.
    out = run(machine, f"if {is_container}; then {docker}; else echo __UNIT__; fi", 90, stdin="")
    if "__UNIT__" not in out:
        return out
    user = run(machine, f"systemctl --user {action} {n}", 60, stdin="")
    if user.startswith("exit 0"):
        return user + f"\n(user service {name} {action}ed)"
    return run(machine, unit, 90, sudo=True)
