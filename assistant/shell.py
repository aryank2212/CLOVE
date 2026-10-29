"""Persistent shell session for Clove."""
import os
import pty
import select
import subprocess
import time
from pathlib import Path


class PersistentShell:
    def __init__(self, cwd: str = None):
        self.cwd = Path(cwd or Path.home())
        self.master, self.slave = pty.openpty()
        self.proc = subprocess.Popen(
            ['/bin/bash', '--norc', '--noprofile'],
            stdin=self.slave,
            stdout=self.slave,
            stderr=self.slave,
            cwd=str(self.cwd),
            env={**os.environ, 'PS1': '$ ', 'TERM': 'dumb'},
            start_new_session=True,
        )
        os.close(self.slave)
        # Set non-blocking
        import fcntl
        fcntl.fcntl(self.master, fcntl.F_SETFL, os.O_NONBLOCK)
        time.sleep(0.3)
        self._read_all()  # clear initial output
        self._send('export PS1="$ "\n')
        time.sleep(0.1)
        self._read_all()

    def _read_all(self, timeout=0.5):
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
        os.write(self.master, cmd.encode('utf-8'))

    def run(self, command: str, timeout: int = 120) -> str:
        # Mark end of command
        marker = f'__CLOVE_DONE_{time.time_ns()}__'
        self._send(f'{command}\necho "{marker}:$?"\n')
        end = time.time() + timeout
        buf = ''
        while time.time() < end:
            try:
                data = os.read(self.master, 4096).decode('utf-8', errors='replace')
                if not data:
                    break
                buf += data
                if marker in buf:
                    break
            except BlockingIOError:
                time.sleep(0.01)
                continue
            except OSError:
                break
        # Extract result
        if marker in buf:
            idx = buf.rfind(marker)
            result = buf[:idx]
            rest = buf[idx:]
            # Get exit code
            if ':' in rest:
                try:
                    code = rest.split(':', 1)[1].strip().split('\n')[0]
                except:
                    code = '?'
            else:
                code = '?'
            # Clean up prompts
            result = result.strip()
            return f'exit {code}\n{result[-4000:]}'
        return f'timeout\n{buf[-2000:]}'

    def close(self):
        try:
            self.proc.terminate()
            self.proc.wait(timeout=2)
        except:
            try:
                self.proc.kill()
            except:
                pass
        try:
            os.close(self.master)
        except:
            pass


_shell = None


def get_shell():
    global _shell
    if _shell is None or _shell.proc.poll() is not None:
        _shell = PersistentShell()
    return _shell
