from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("LOCAL_IPTV_HOME", str(Path.home() / ".local-iptv"))).expanduser()
PID_FILE = DATA_DIR / "server.pid"
LOG_FILE = DATA_DIR / "server.log"
HOST = os.environ.get("LOCAL_IPTV_HOST", "127.0.0.1")
PORT = int(os.environ.get("LOCAL_IPTV_PORT", "8766"))
BASE_URL = f"http://{HOST}:{PORT}"


def health(timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(f"{BASE_URL}/api/health", headers={"User-Agent": "LocalIPTVLauncher/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("status") == "ok"
    except (OSError, ValueError, urllib.error.URLError):
        return False


def read_pid() -> int | None:
    try:
        return int(PID_FILE.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def process_exists(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except OSError:
        return False


def write_pid(pid: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(DATA_DIR, 0o700)
    except OSError:
        pass
    temp = PID_FILE.with_suffix(".tmp")
    temp.write_text(f"{pid}\n", encoding="ascii")
    temp.replace(PID_FILE)


def clear_pid() -> None:
    try:
        PID_FILE.unlink()
    except FileNotFoundError:
        pass


def status() -> int:
    pid = read_pid()
    if health():
        print(f"Local IPTV is running at {BASE_URL}")
        if pid:
            print(f"PID: {pid}")
        return 0
    if pid and process_exists(pid):
        print(f"A process (PID {pid}) is recorded, but Local IPTV is not responding at {BASE_URL}.")
        print(f"Check log: {LOG_FILE}")
        return 1
    clear_pid()
    print("Local IPTV is stopped.")
    return 3


def start() -> int:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if health():
        print(f"Local IPTV is already running at {BASE_URL}")
        webbrowser.open(BASE_URL)
        return 0

    old_pid = read_pid()
    if old_pid and process_exists(old_pid):
        print(f"A process (PID {old_pid}) is recorded but the health endpoint is not responding.")
        print(f"Check log: {LOG_FILE}")
        return 1
    clear_pid()

    python_exe = os.environ.get("LOCAL_IPTV_PYTHON", sys.executable)
    log = LOG_FILE.open("ab", buffering=0)
    kwargs: dict = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL, "stdout": log, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = getattr(subprocess, "DETACHED_PROCESS", 0x00000008) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        kwargs["close_fds"] = True
    else:
        kwargs["start_new_session"] = True
        kwargs["close_fds"] = True

    try:
        child = subprocess.Popen([python_exe, str(ROOT / "run.py")], **kwargs)
    finally:
        log.close()
    write_pid(child.pid)

    deadline = time.monotonic() + 25
    while time.monotonic() < deadline:
        if health(timeout=1):
            print(f"Local IPTV started at {BASE_URL}")
            print(f"PID: {child.pid}")
            print(f"Log: {LOG_FILE}")
            webbrowser.open(BASE_URL)
            return 0
        if child.poll() is not None:
            clear_pid()
            print("Local IPTV failed to start. Last log lines:")
            try:
                lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
                print("\n".join(lines[-30:]))
            except OSError:
                pass
            return 1
        time.sleep(0.25)

    print(f"Local IPTV process started (PID {child.pid}) but did not become healthy within 25 seconds.")
    print(f"Check log: {LOG_FILE}")
    return 1


def stop() -> int:
    pid = read_pid()
    if health() and not pid:
        print("Local IPTV is responding, but no PID file exists. Refusing to stop an unidentified process.")
        return 1
    if not pid or not process_exists(pid):
        clear_pid()
        if health():
            print("Local IPTV is responding, but its process is not recorded; stop it from the terminal that launched it.")
            return 1
        print("Local IPTV is already stopped.")
        return 0

    try:
        os.kill(pid, signal.SIGTERM)
    except OSError as exc:
        print(f"Could not stop Local IPTV (PID {pid}): {exc}")
        return 1

    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if not process_exists(pid):
            clear_pid()
            print("Local IPTV stopped.")
            return 0
        time.sleep(0.2)

    try:
        os.kill(pid, signal.SIGKILL)
    except (OSError, AttributeError):
        pass
    time.sleep(0.3)
    if not process_exists(pid):
        clear_pid()
        print("Local IPTV stopped.")
        return 0
    print(f"Could not confirm that PID {pid} stopped. Check the process manually.")
    return 1


def main() -> int:
    action = sys.argv[1].lower() if len(sys.argv) > 1 else "start"
    if action in ("start", "run"):
        return start()
    if action == "status":
        return status()
    if action == "stop":
        return stop()
    print("Usage: launcher.py [start|status|stop]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
