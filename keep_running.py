"""
================================================================
  WATCHDOG - keeps the signal app alive 24/7.

  The desktop shortcut now starts THIS file. It launches app.py
  and restarts it automatically whenever the app dies for an
  unknown reason (crash, kill, power blip ...). When YOU quit the
  app on purpose (Quit button / mini bar), app.py writes
  _app_quit.flag first - the watchdog sees it, deletes it and
  stops as well.

  Run:  pythonw keep_running.py
================================================================
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.join(HERE, "app.py")
FLAG = os.path.join(HERE, "_app_quit.flag")
LOG = os.path.join(HERE, "_watchdog.log")

MIN_LIFE = 20      # seconds - below this it counts as a failed start
MAX_FAST = 5       # give up after this many failed starts in a row
SLEEP = 3          # seconds to wait before restarting


def note(msg):
    line = f"{time.strftime('%Y-%m-%d %H:%M:%S')}  {msg}\n"
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
    print(line, end="", flush=True)


def single_instance():
    """Only ONE watchdog may run (two would fight over restarts)."""
    if sys.platform != "win32":
        return True
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = k32.CreateMutexW(None, False, r"Local\TenupFutureWatchdog")
        if not handle:
            return True
        return ctypes.get_last_error() != 183     # 183 = already exists
    except Exception:
        return True


def main():
    if not single_instance():
        return 0
    note("watchdog started")
    fast = 0
    while True:
        t0 = time.time()
        try:
            proc = subprocess.Popen([sys.executable, APP], cwd=HERE)
        except OSError as e:
            note(f"cannot launch app: {e}")
            time.sleep(SLEEP)
            continue
        proc.wait()
        life = time.time() - t0
        intentional = os.path.exists(FLAG)
        try:
            os.remove(FLAG)
        except OSError:
            pass
        if intentional:
            note(f"app quit on purpose (ran {life:.0f}s) - watchdog stops")
            return 0
        note(f"app died by itself after {life:.0f}s "
             f"(exit {proc.returncode}) - restarting in {SLEEP}s")
        if life < MIN_LIFE:
            fast += 1
            if fast >= MAX_FAST:
                note("too many failed starts in a row - giving up, "
                     "check app_console.log / app_crash.log")
                return 1
        else:
            fast = 0
        time.sleep(SLEEP)


if __name__ == "__main__":
    sys.exit(main())
