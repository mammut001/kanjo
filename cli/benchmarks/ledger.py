"""Synthetic ledger benchmark. Run from cli: python3 benchmarks/ledger.py [sizes...]."""
import json
import os
import sys
import subprocess
import types
import tempfile
import time
import tracemalloc

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if os.environ.get("KANJO_BENCH_BASELINE"):
    source = subprocess.check_output(["git", "show", "origin/main:cli/kanjo/ledger.py"])
    module = types.ModuleType("kanjo.ledger")
    module.__package__ = "kanjo"
    sys.modules["kanjo.ledger"] = module
    exec(compile(source, "origin/main:cli/kanjo/ledger.py", "exec"), module.__dict__)
from kanjo.cache import _dump_session, _load_session
from kanjo.export import scan, build_export
from kanjo.ledger import Ledger, entry_key
from kanjo.sources.base import Message, Session


def timed(fn):
    start = time.perf_counter()
    value = fn()
    return value, time.perf_counter() - start


def bench(n):
    with tempfile.TemporaryDirectory(prefix="kanjo-bench-") as root:
        os.environ["KANJO_DATA_DIR"] = os.path.join(root, "data")
        os.environ["KANJO_CACHE_DIR"] = os.path.join(root, "cache")
        os.makedirs(os.environ["KANJO_DATA_DIR"])
        path = os.path.join(root, "missing.jsonl")
        entries = {}
        for i in range(n):
            sid = "session-%08d" % i
            s = Session(id=sid, agent="claude", file=path, started=1700000000.0 + i,
                        ended=1700000001.0 + i, cwd=root, title="Synthetic coding session",
                        messages=[Message(1700000000.0 + i, "claude-sonnet-4-5", 1200, 200,
                                          3000, 100, key="message-%08d" % i)])
            entries[entry_key(s.agent, sid, None)] = {"session": _dump_session(s), "source_path": path,
                "source_paths": [path], "imported_at": "2026-01-01T00:00:00Z", "file_sig": [[123, 123], None]}
        ledger = Ledger()
        ledger.entries = entries
        ledger.dirty = True
        _, rewrite = timed(ledger.save)
        size = os.path.getsize(ledger.path)
        del entries, ledger
        tracemalloc.start()
        ledger, load = timed(Ledger)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        keys = list(ledger._known_keys)[:100]
        sessions = [_load_session(ledger._meta_orphans[k]) for k in keys]
        # Force real changed entries while retaining the same source path.
        for s in sessions:
            s.messages[0].output += 1
        def update():
            if hasattr(ledger, "prepare_updates"):
                ledger.prepare_updates(keys)
            for session in sessions:
                ledger.note_file(session, path)
        _, merge = timed(update)
        _, append = timed(ledger.save)
        journal_size = os.path.getsize(ledger.journal_path)
        _, scan_time = timed(lambda: scan({}, ledger=Ledger()))
        _, export_time = timed(lambda: build_export(dirs={}, home=root, tokei_dir=os.path.join(root, "none")))
        print(json.dumps(dict(sessions=n, bytes=size, load_s=load, load_peak_mib=peak / 1048576,
                              rewrite_s=rewrite, changed_100_s=merge, append_s=append,
                              journal_bytes=journal_size, scan_s=scan_time, export_s=export_time)), flush=True)


if __name__ == "__main__":
    for size in map(int, sys.argv[1:] or (20000, 50000, 100000)):
        bench(size)
