"""Tests for the edges of the fetch lock: a lock that cannot be made or taken over ends the run with a message, never a traceback.

The main behaviour (one run at a time, a pid in the file, a stale lock taken over) is in test_eqlwiki_fetch.py.
"""

import os
import subprocess
import sys
import threading
import time
from datetime import date
from pathlib import Path

import pytest

from trioforge.sources import eqlwiki


class NoNetwork:
    """A transport that must never be asked for anything."""

    def __call__(self, url, headers):
        raise AssertionError("no request may be made when the lock is refused")


def client():
    from trioforge.sources.http import PoliteClient

    return PoliteClient("TrioForge-extractor/0.1 (non-commercial fan project; 1 request/s)", transport=NoNetwork(), honour_robots=False)


def run(tmp_path, monkeypatch, lock_path):
    monkeypatch.setattr(eqlwiki, "LOCK_PATH", lock_path)
    return eqlwiki.main(["fetch", "--out", str(tmp_path / "2026-10-13")], client=client(), today=date(2026, 10, 14))


def test_a_lock_folder_that_cannot_be_made_is_a_refusal_with_a_message(tmp_path, monkeypatch, capsys):
    blocker = tmp_path / "sources"
    blocker.write_text("this is a file, not a folder", encoding="ascii")
    assert run(tmp_path, monkeypatch, blocker / ".eqlwiki.lock") == 2
    error = capsys.readouterr().err
    assert error.startswith("error: ") and "lock" in error and "Traceback" not in error


def test_a_lock_file_that_cannot_be_created_is_a_refusal_with_a_message(tmp_path, monkeypatch, capsys):
    def denied(path, flags, *args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "open", denied)
    assert run(tmp_path, monkeypatch, tmp_path / "locks" / ".eqlwiki.lock") == 2
    assert "lock" in capsys.readouterr().err


def test_a_stale_lock_that_cannot_be_taken_over_is_a_refusal_not_a_crash(tmp_path, monkeypatch, capsys):
    # a stale lock is no longer removed and made again (two runs could do that to each other's new lock): it is
    # locked where it stands and gets the new process id, so what can fail is opening it for writing
    lock = tmp_path / ".eqlwiki.lock"
    lock.write_text("999999999\n", encoding="ascii")  # a process id nobody has

    def refuse(path, flags, *args, **kwargs):
        if flags & os.O_EXCL:
            raise FileExistsError(17, "File exists")  # the lock file is there: it is to be taken over
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "open", refuse)
    monkeypatch.setattr(eqlwiki, "_pid_alive", lambda pid: False)
    assert run(tmp_path, monkeypatch, lock) == 2
    error = capsys.readouterr().err
    assert error.startswith("error: ") and "lock" in error and "Traceback" not in error


def test_an_empty_lock_file_just_made_by_another_run_is_respected(tmp_path, monkeypatch, capsys):
    lock = tmp_path / ".eqlwiki.lock"
    lock.write_text("", encoding="ascii")  # created, the process id not written yet
    assert run(tmp_path, monkeypatch, lock) == 2
    assert "another fetch is running" in capsys.readouterr().err
    assert lock.exists()


def test_the_lock_can_be_given_a_process_id_and_a_liveness_check():
    # FetchLock(path, pid=..., alive=...) lets a test stand in for another process
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / ".eqlwiki.lock"
        path.write_text("4242\n", encoding="ascii")
        with pytest.raises(eqlwiki._Refusal, match="process 4242"):
            eqlwiki.FetchLock(path, pid=7, alive=lambda pid: pid == 4242).acquire()
        lock = eqlwiki.FetchLock(path, pid=7, alive=lambda pid: False)
        lock.acquire()
        assert path.read_text(encoding="ascii").strip() == "7"
        lock.release()
        assert not path.exists()


# ---- the lock is held by the operating system, not by a file that can be taken over twice -------------------------
# A second run that finds a stale lock file must never be able to delete the lock that a third run has just made:
# the file only says (for the message) who holds the lock; the hold itself is an OS lock on the open handle.


def stale_lock(tmp_path, pid="999999"):
    path = tmp_path / ".eqlwiki.lock"
    path.write_text(f"{pid}\n", encoding="ascii")  # left behind by a run that crashed
    return path


def test_two_runs_that_find_one_stale_lock_never_both_hold_it(tmp_path):
    # run B has read the stale lock and stops before it acts; run A starts and ends its attempt meanwhile
    path = stale_lock(tmp_path)
    alive = lambda pid: pid in (1, 2)  # the stale process 999999 is dead; the two stand-ins are alive
    paused, go = threading.Event(), threading.Event()

    class SlowB(eqlwiki.FetchLock):
        first = True

        def _owner(self):
            owner = super()._owner()
            if SlowB.first:
                SlowB.first = False
                paused.set()
                assert go.wait(10)
            return owner

    b = SlowB(path, pid=2, alive=alive)
    failure = []

    def run_b():
        try:
            b.acquire()
        except eqlwiki._Refusal as error:
            failure.append(error)

    thread = threading.Thread(target=run_b)
    thread.start()
    assert paused.wait(10)
    a = eqlwiki.FetchLock(path, pid=1, alive=alive)
    refused = None
    try:
        a.acquire()
    except eqlwiki._Refusal as error:
        refused = error
    go.set()
    thread.join(10)
    holders = [lock for lock in (a, b) if lock._held]
    assert len(holders) == 1, f"{len(holders)} runs hold the lock"
    assert path.read_text(encoding="ascii").strip() == str(1 if holders[0] is a else 2)
    assert (refused is None) != (not failure)  # the run that did not get the lock was told so
    holders[0].release()
    assert not path.exists()


def test_a_lock_that_looks_stale_but_is_held_by_a_live_run_is_respected(tmp_path):
    path = tmp_path / ".eqlwiki.lock"
    first = eqlwiki.FetchLock(path, pid=11, alive=lambda pid: False)
    first.acquire()
    path.write_text("999999\n", encoding="ascii")  # the file now names a dead process, the first run still holds the lock
    second = eqlwiki.FetchLock(path, pid=12, alive=lambda pid: False)
    with pytest.raises(eqlwiki._Refusal, match="another fetch is running"):
        second.acquire()
    assert not second._held and first._held
    first.release()


def test_the_refusal_names_the_process_that_holds_the_lock(tmp_path):
    path = tmp_path / ".eqlwiki.lock"
    with eqlwiki.FetchLock(path, pid=4242):
        with pytest.raises(eqlwiki._Refusal, match="process 4242"):
            eqlwiki.FetchLock(path, pid=7).acquire()


def test_a_run_that_is_refused_does_not_disturb_the_run_that_holds_the_lock(tmp_path):
    path = tmp_path / ".eqlwiki.lock"
    with eqlwiki.FetchLock(path, pid=4242):
        for _ in range(3):
            with pytest.raises(eqlwiki._Refusal):
                eqlwiki.FetchLock(path, pid=7).acquire()
        assert path.read_text(encoding="ascii").strip() == "4242"
    assert not path.exists()


def test_a_lock_file_that_cannot_be_removed_at_the_end_does_not_end_the_run_with_a_traceback(tmp_path, monkeypatch):
    path = tmp_path / ".eqlwiki.lock"
    lock = eqlwiki.FetchLock(path)
    lock.acquire()

    def busy(self, *args, **kwargs):
        raise PermissionError(13, "in use by another process")

    monkeypatch.setattr(type(path), "unlink", busy)
    lock.release()  # must not raise
    monkeypatch.undo()
    assert path.exists()
    with eqlwiki.FetchLock(path, pid=99, alive=lambda pid: False):  # and the lock is free again
        pass


CHILD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from pathlib import Path
from trioforge.sources import eqlwiki
print("ready", flush=True)
while not Path(sys.argv[3]).exists():  # every child has started: go
    time.sleep(0.001)
lock = eqlwiki.FetchLock(Path(sys.argv[2]))
try:
    lock.acquire()
except eqlwiki._Refusal:
    print("refused", flush=True)
else:
    print("holds", flush=True)
    while not Path(sys.argv[4]).exists():  # keep it until every child has answered
        time.sleep(0.01)
    lock.release()
"""


def test_eight_processes_that_start_together_on_a_stale_lock_give_it_to_exactly_one(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    path = stale_lock(tmp_path, pid=str(dead_process_id()))
    go, done = tmp_path / "go", tmp_path / "done"
    source = str(Path(eqlwiki.__file__).resolve().parents[1].parent)
    children = [
        subprocess.Popen([sys.executable, "-c", CHILD, source, str(path), str(go), str(done)], stdout=subprocess.PIPE, text=True)
        for _ in range(8)
    ]
    pool = ThreadPoolExecutor(max_workers=8)
    try:
        ready = [future.result(timeout=120).strip() for future in [pool.submit(child.stdout.readline) for child in children]]
        assert ready == ["ready"] * 8
        go.write_text("go", encoding="ascii")
        answers = [future.result(timeout=120).strip() for future in [pool.submit(child.stdout.readline) for child in children]]
        done.write_text("done", encoding="ascii")  # the holder lets go only now, so no child can come late and get it
        for child in children:
            assert child.wait(timeout=60) == 0
    finally:
        done.write_text("done", encoding="ascii")
        for child in children:
            child.kill()  # a child that is still alive after a failure would keep a reader thread waiting
        pool.shutdown(wait=True)
        for child in children:
            child.stdout.close()
    assert answers.count("holds") == 1 and answers.count("refused") == 7, answers
    assert not path.exists()


def dead_process_id():
    done = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True, check=True)
    return int(done.stdout)
