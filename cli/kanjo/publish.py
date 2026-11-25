"""Publish usage command: ``kanjo publish-usage``.

Publishes public usage summary to a git repository (CONTRACT.md section 12).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from typing import Optional

from .config import Config, ConfigError, load as load_config
from .export import (
    build_public_summary,
    load_fast_public_summary,
    save_fast_public_summary,
    source_fingerprint,
)


def _config(args) -> Config:
    return load_config(getattr(args, "config", None))


def _cache(args):
    if getattr(args, "no_cache", False):
        return None
    from .cache import SessionCache
    return SessionCache()


def _error(message: str) -> int:
    output = {"status": "error", "message": message}
    print(json.dumps(output))
    return 1


def _git(repo: str, *args: str, env: Optional[dict] = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True, encoding="utf-8", check=False, env=env)


def _git_error(res: subprocess.CompletedProcess) -> str:
    return res.stderr.strip() or res.stdout.strip()


def _week_key(doc: dict) -> str:
    if doc.get("weeks"):
        return doc["weeks"][-1]["period"]
    return doc.get("all_time", {}).get("period", "all")


def _remote_tip(repo: str, branch: str) -> Optional[str]:
    res = _git(repo, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/%s^{commit}" % branch)
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else None


def _fetch(repo: str, branch: str) -> Optional[str]:
    """Update origin/<branch>. Returns an error or None."""
    res = _git(repo, "fetch", "--quiet", "origin",
               "+refs/heads/%s:refs/remotes/origin/%s" % (branch, branch))
    if res.returncode != 0:
        return "git fetch failed: %s" % _git_error(res)
    return None


def _same_data(repo: str, base: str, file_rel: str, doc: dict) -> bool:
    """True if <base>:<file_rel> already holds ``doc`` (``generated_at`` aside)."""
    res = _git(repo, "show", "%s:%s" % (base, file_rel))
    if res.returncode != 0:
        return False
    try:
        existing = json.loads(res.stdout)
    except ValueError:
        return False
    if not isinstance(existing, dict):
        return False
    strip = lambda d: {k: v for k, v in d.items() if k != "generated_at"}
    return strip(existing) == strip(doc)


def _commit_on(repo: str, base: str, file_rel: str, payload: str, message: str):
    """Make a commit on top of ``base`` that only replaces ``file_rel``. Returns (sha, error).

    Plumbing only, with a throwaway index: the user's checkout, branch, index and
    uncommitted work in the website repo are never touched, whatever branch they are on.
    """
    # Bytes, not text: on Windows text-mode stdin would turn "\n" into "\r\n".
    blob_res = subprocess.run(["git", "-C", repo, "hash-object", "-w", "--stdin"],
                              input=payload.encode("utf-8"), capture_output=True, check=False)
    if blob_res.returncode != 0:
        return None, "git hash-object failed: %s" % blob_res.stderr.decode("utf-8", "replace").strip()
    blob_sha = blob_res.stdout.decode("ascii", "replace").strip()
    tmp = tempfile.mkdtemp(prefix="kanjo-publish-")
    try:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        path = os.path.normpath(file_rel).replace(os.sep, "/")
        for args in (("read-tree", base),
                     ("update-index", "--add", "--cacheinfo", "100644,%s,%s" % (blob_sha, path))):
            res = _git(repo, *args, env=env)
            if res.returncode != 0:
                return None, "git %s failed: %s" % (args[0], _git_error(res))
        tree = _git(repo, "write-tree", env=env)
        if tree.returncode != 0:
            return None, "git write-tree failed: %s" % _git_error(tree)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    commit = _git(repo, "commit-tree", tree.stdout.strip(), "-p", base, "-m", message)
    if commit.returncode != 0:
        return None, "git commit-tree failed: %s" % _git_error(commit)
    return commit.stdout.strip(), None


def _push_commit(repo: str, sha: str, branch: str) -> subprocess.CompletedProcess:
    return _git(repo, "push", "origin", "%s:refs/heads/%s" % (sha, branch))


def cmd_publish_usage(args) -> int:
    repo = os.path.abspath(args.repo)
    file_rel = args.file
    branch = args.branch
    dry_run = getattr(args, "dry_run", False)

    if not os.path.isdir(repo):
        return _error("repository directory does not exist: %s" % repo)

    res = _git(repo, "rev-parse", "--is-inside-work-tree")
    if res.returncode != 0 or res.stdout.strip() != "true":
        return _error("%s is not a git repository" % repo)

    # The summary is committed straight onto origin/<branch>, so the branch checked out
    # in the website repo (and any uncommitted work there) does not matter.
    if not dry_run:
        err = _fetch(repo, branch)
        if err:
            return _error(err)

    cfg = _config(args)
    doc = None
    fp = None
    use_cache = not getattr(args, "no_cache", False)
    if use_cache:
        fp = source_fingerprint(config=cfg)
        doc = load_fast_public_summary(fp)
    if doc is None:
        doc = build_public_summary(config=cfg, cache=_cache(args))
        if use_cache:
            if fp is None:
                fp = source_fingerprint(config=cfg)
            save_fast_public_summary(fp, doc)

    base = _remote_tip(repo, branch)
    if base is not None and _same_data(repo, base, file_rel, doc):
        print(json.dumps({"status": "unchanged"}))
        return 0

    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    if dry_run:
        sys.stdout.write(payload)
        return 0
    if base is None:
        return _error("remote branch 'origin/%s' does not exist" % branch)

    week_key = _week_key(doc)
    message = "chore: update AI token usage (%s)" % week_key
    sha, err = _commit_on(repo, base, file_rel, payload, message)
    if err:
        return _error(err)
    push = _push_commit(repo, sha, branch)
    if push.returncode != 0:
        # The remote moved on (another machine, a bot): rebuild on the new tip once.
        err = _fetch(repo, branch)
        if err:
            return _error("git push failed: %s" % _git_error(push))
        base = _remote_tip(repo, branch)
        if base is not None and _same_data(repo, base, file_rel, doc):
            print(json.dumps({"status": "unchanged"}))
            return 0
        if base is None:
            return _error("git push failed: %s" % _git_error(push))
        sha, err = _commit_on(repo, base, file_rel, payload, message)
        if err:
            return _error(err)
        retry = _push_commit(repo, sha, branch)
        if retry.returncode != 0:
            return _error("git push retry failed: %s" % _git_error(retry))
    _git(repo, "update-ref", "refs/remotes/origin/%s" % branch, sha)

    print(json.dumps({"status": "pushed", "commit": sha, "file": file_rel, "period": week_key}))
    return 0
