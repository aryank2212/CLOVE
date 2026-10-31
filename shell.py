"""Persistent shell session for Clove."""
import os
import subprocess
import time
from pathlib import Path

try:
    import pty
    import select
    import fcntl
    _HAS_PTY = True
except ImportError:
    _HAS_PTY = False


class PersistentShell:
    def __init__(self, cwd: str = None):
        self.cwd = Path(cwd or Path.home())
        if _HAS_PTY:
            self.master, self.slave = pty.openpty()
            self.proc = subprocess.Popen(
                ['/bin/bash', '--norc', '--noprofile'],
                stdin=self.slave, stdout=self.slave, stderr=self.slave,
                cwd=str(self.cwd), env={**os.environ, 'PS1': '$ ', 'TERM': 'dumb'},
                start_new_session=True,
            )
            os.close(self.slave)
            fcntl.fcntl(self.master, fcntl.F_SETFL, os.O_NONBLOCK)
            time.sleep(0.3)
            self._read_all()
            self._send('export PS1="$ "\n')
            time.sleep(0.1)
            self._read_all()
        else:
            self.proc = None
            self._buf = ""
            # Windows: use cmd.exe via subprocess per run (no true persistence, but functional)
            self._shell_exe = os.environ.get("COMSPEC", "cmd.exe")

    def _read_all(self, timeout=0.5):
        if not _HAS_PTY:
            return ""
        out = b''
        end = time.time() + timeout
        while time.time() < end:
            r, _, _ = select.select([self.master], [], [], 0.05)
            if not r:
                break
            try:
                data = os.read(self.master, 4096)
                if not data:
                    break
                out += data
            except (OSError, BlockingIOError):
                break
        return out.decode('utf-8', errors='replace')

    def _send(self, cmd):
        if _HAS_PTY:
            os.write(self.master, cmd.encode('utf-8'))

    def run(self, command: str, timeout: int = 120) -> str:
        if _HAS_PTY:
            marker = f'__CLOVE_DONE_{time.time_ns()}__'
            self._send(f'{command}\necho "{marker}:$?"\n')
            end = time.time() + timeout
            buf = ''
            while time.time() < end:
                try:
                    data = os.read(self.master, 4096).decode('utf-8', errors='replace')
                    buf += data
                    if marker in buf:
                        break
                except (OSError, BlockingIOError):
                    time.sleep(0.05)
            # extract exit code
            import re
            m = __import__('re').search(rf'{marker}:(\d+)', buf)
            rc = m.group(1) if m else '?'
            # clean marker line
            out = buf.split(marker)[0]
            return f"exit {rc}\n{out.strip()[-2500:]}"
        # Windows fallback
        try:
            r = subprocess.run(command, shell=True, capture_output=True, text=True,
                               timeout=timeout, cwd=str(self.cwd))
            out = (r.stdout + r.stderr).strip()
            return f"exit {r.returncode}\n{out[-2500:]}"
        except subprocess.TimeoutExpired:
            return f"timed out after {timeout}s"
        except Exception as e:
            return f"error: {e}"

    def close(self):
        if _HAS_PTY:
            try:
                self.proc.terminate()
            except Exception:
                pass


_shell = None


def get_shell():
    global _shell
    if _shell is None or (_HAS_PTY and _shell.proc.poll() is not None) or (not _HAS_PTY and _shell is None):
        _shell = PersistentShell()
    return _shell
