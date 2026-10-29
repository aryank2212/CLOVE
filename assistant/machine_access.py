"""Machine access: sudo-backed commands for Clove (full control mode)."""
import os
import subprocess
import logging

log = logging.getLogger("clove.machine_access")

def sudo_password() -> str:
    v = os.environ.get("SUDO_PASSWORD", "")
    if not v:
        try:
            import config
            v = getattr(config, "SUDO_PASSWORD", "")
        except Exception:
            pass
    return v

def sudo_run(command: str, timeout: int = 120) -> str:
    pw = sudo_password()
    if not pw:
        return "error: SUDO_PASSWORD not set; full machine access disabled"
    try:
        proc = subprocess.run(
            ["sudo", "-S", "bash", "-c", command],
            input=pw + "\n", capture_output=True, text=True, timeout=timeout)
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return f"error (rc={proc.returncode}): {err or out}"
        return out or "(done)"
    except subprocess.TimeoutExpired:
        return f"error: timed out after {timeout}s"
    except Exception as e:
        return f"error: {e}"

def full_access_enabled() -> bool:
    return bool(sudo_password())
