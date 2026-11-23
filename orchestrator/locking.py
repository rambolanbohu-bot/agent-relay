#!/usr/bin/env python3
"""Agent Relay Skill v1.0.0-rc2 — 跨平台排他文件锁（locking.py）.

RC2 安全修复（ChatGPT 审查 Security-1）：
RC1 的 file_log.py 用“锁文件超过 60 秒就删掉”的办法处理旧锁——
一个活着的写入者可能正在写，另一个进程却把它的锁删了，两个写入者
会同时写，日志就可能损坏。

本模块的规则：
- 锁由操作系统持有（POSIX: fcntl.flock；Windows: msvcrt.locking），
  进程死掉时操作系统自动释放锁——**永远不需要靠时间删锁**，
  也就永远不会删掉一个活进程的锁。
- 锁文件本身永不删除（它只是一个锚点，锁在文件描述符/句柄上）。
- 锁文件里写持有者的 PID，只用于诊断，不用于决定是否抢锁。
- 只有在“确认持有者进程已死”的情况下才允许抢锁：
  POSIX 用 os.kill(pid, 0) 判断；Windows 用 ctypes OpenProcess 判断。
  判断不出来（权限不足、平台不支持）时，宁可等超时报错，也绝不抢锁。
- 抢锁只在“持有者已死且操作系统锁仍被占着”这种极端残留情况下才
  发生；正常情况下根本不需要抢锁（进程死了锁就自动释放了）。

用法：
    from locking import FileLock
    with FileLock("/path/to/state.lock", timeout=10):
        ...  # 临界区，同一时间只有一个持有者
"""

import os
import sys
import time

LOCK_POLL_SECONDS = 0.05


def _pid_alive(pid):
    """True if a process with this PID is (probably) alive.

    Returns None when liveness cannot be determined (then the caller must
    treat it as alive — never steal a lock we cannot prove is dead).
    """
    if not pid or pid <= 0:
        return None
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes

            kernel32 = ctypes.windll.kernel32
            # PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                # No such process (or access denied — ambiguous).
                err = kernel32.GetLastError()
                # ERROR_INVALID_PARAMETER (87) / ERROR_FILE_NOT_FOUND mean
                # the PID does not exist; anything else is ambiguous.
                if err in (87, 2):
                    return False
                return None
            kernel32.CloseHandle(handle)
            return True
        except Exception:
            return None
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we may not signal it.
        return True
    except OSError:
        return None


def _read_lock_pid(lock_path):
    try:
        with open(lock_path, "r", encoding="ascii") as f:
            return int(f.read().strip() or "0")
    except (OSError, ValueError):
        return 0


class FileLock:
    """Cross-platform exclusive file lock.

    The lock is held by the OS (flock / msvcrt.locking), so it is released
    automatically when the holder process dies. The lock file is never
    deleted by age — that was the RC1 bug.
    """

    def __init__(self, lock_path, timeout=10):
        self.lock_path = lock_path
        self.timeout = timeout
        self._fd = None
        self._is_windows = os.name == "nt"

    def __enter__(self):
        # Open (creating if needed) the lock file; the OS lock is taken on
        # this open file description, not on the path.
        os.makedirs(os.path.dirname(os.path.abspath(self.lock_path)),
                    exist_ok=True)
        self._fd = os.open(self.lock_path,
                           os.O_CREAT | os.O_RDWR, 0o644)
        deadline = time.time() + self.timeout
        while True:
            if self._try_acquire():
                try:
                    os.ftruncate(self._fd, 0)
                    os.write(self._fd, str(os.getpid()).encode("ascii"))
                    os.fsync(self._fd)
                except OSError:
                    pass
                return self
            if time.time() >= deadline:
                os.close(self._fd)
                self._fd = None
                raise TimeoutError(
                    f"could not acquire lock {self.lock_path} "
                    f"within {self.timeout}s (another writer active?)")
            # Before waiting longer, check whether the recorded holder is
            # provably dead. If so, the OS lock is a leftover from a crashed
            # holder on a filesystem that did not release it — only then may
            # we attempt a steal, and only once per wait cycle.
            pid = _read_lock_pid(self.lock_path)
            if pid and _pid_alive(pid) is False:
                self._steal_if_stale()
            time.sleep(LOCK_POLL_SECONDS)

    def _try_acquire(self):
        if self._is_windows:
            try:
                import msvcrt
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        try:
            import fcntl
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (OSError, ImportError):
            return False

    def _steal_if_stale(self):
        """Last-resort recovery for a lock whose holder is provably dead.

        The OS normally releases the lock when the holder dies, so this
        path should almost never run. When it does, we close and reopen the
        file description and retry the OS lock once. We NEVER unlink the
        lock file: unlinking by path cannot distinguish a live holder from
        a dead one.
        """
        try:
            os.close(self._fd)
        except OSError:
            pass
        self._fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR, 0o644)

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False

    def release(self):
        if self._fd is None:
            return
        try:
            if self._is_windows:
                import msvcrt
                try:
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                try:
                    import fcntl
                    fcntl.flock(self._fd, fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            try:
                os.close(self._fd)
            except OSError:
                pass
            self._fd = None
            # NOTE: the lock file is deliberately NOT deleted. Deleting it
            # by age was the RC1 bug (Security-1): a live writer's lock
            # could be removed by another process. The OS lock on the open
            # file description is the real lock; the file on disk is only
            # an anchor and is harmless to keep.


def lock_path_for(state_path):
    """Lock file path for a given state/log file."""
    return state_path + ".lock"


if __name__ == "__main__":
    # Tiny self-check: acquire, hold briefly, release; second acquire works.
    import tempfile

    with tempfile.TemporaryDirectory() as d:
        lp = os.path.join(d, "test.lock")
        with FileLock(lp, timeout=5):
            print("lock acquired, pid written:", _read_lock_pid(lp))
        with FileLock(lp, timeout=5):
            print("lock re-acquired after release: ok")
    print("locking self-check: ok")
    sys.exit(0)
