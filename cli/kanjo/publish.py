"""Publish usage command: ``kanjo publish-usage``.

Publishes public usage summary to a git repository (CONTRACT.md section 12).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
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


def _git(repo: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", repo] + list(args),
                          capture_output=True, text=True, check=False)


def _git_error(res: subprocess.CompletedProcess) -> str:
    return res.stderr.strip() or res.stdout.strip()


def _unpushed_commits(repo: str, branch: str) -> int:
    """Commits on HEAD that origin/<branch> does not have, e.g. left by an earlier failed push."""
    res = _git(repo, "rev-list", "--count", "origin/%s..HEAD" % branch)
    if res.returncode != 0:
        return 0
    try:
        return int(res.stdout.strip() or "0")
    except ValueError:
        return 0


def _push(repo: str, branch: str) -> Optional[str]:
    """Push HEAD to origin/<branch>, rebasing once if the remote moved. Returns an error or None."""
    if _git(repo, "push", "origin", branch).returncode == 0:
        return None
    # --autostash: unrelated uncommitted edits in the website repo must not block the retry.
    rebase_res = _git(repo, "pull", "--rebase", "--autostash", "origin", branch)
    if rebase_res.returncode != 0:
        return "git pull --rebase failed: %s" % _git_error(rebase_res)
    retry_res = _git(repo, "push", "origin", branch)
    if retry_res.returncode != 0:
        return "git push retry failed: %s" % _git_error(retry_res)
    return None


def _head(repo: str) -> str:
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _week_key(doc: dict) -> str:
    if doc.get("weeks"):
        return doc["weeks"][-1]["period"]
    return doc.get("all_time", {}).get("period", "all")


def cmd_publish_usage(args) -> int:
    repo = os.path.abspath(args.repo)
    file_rel = args.file
    branch = args.branch
    dry_run = getattr(args, "dry_run", False)

    if not os.path.isdir(repo):
        return _error("repository directory does not exist: %s" % repo)

    # 1. Check PATH is a git repository
    res = subprocess.run(["git", "-C", repo, "rev-parse", "--is-inside-work-tree"],
                         capture_output=True, text=True, check=False)
    if res.returncode != 0 or res.stdout.strip() != "true":
        return _error("%s is not a git repository" % repo)

    # Check current branch equals required branch
    res = subprocess.run(["git", "-C", repo, "branch", "--show-current"],
                         capture_output=True, text=True, check=False)
    current_branch = res.stdout.strip()
    if current_branch != branch:
        return _error("current branch '%s' does not match required branch '%s'" % (current_branch, branch))

    # 2. git -C PATH pull --ff-only origin <branch>
    if not dry_run:
        res = subprocess.run(["git", "-C", repo, "pull", "--ff-only", "origin", branch],
                             capture_output=True, text=True, check=False)
        if res.returncode != 0:
            err = res.stderr.strip() or res.stdout.strip()
            return _error("git pull --ff-only failed: %s" % err)

    # 3. Generate public summary
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

    target_path = os.path.join(repo, file_rel)
    existing_doc = None
    if os.path.isfile(target_path):
        try:
            with open(target_path, "r", encoding="utf-8") as f:
                existing_doc = json.load(f)
        except Exception:
            existing_doc = None

    if existing_doc is not None and isinstance(existing_doc, dict):
        ex_cmp = {k: v for k, v in existing_doc.items() if k != "generated_at"}
        new_cmp = {k: v for k, v in doc.items() if k != "generated_at"}
        if ex_cmp == new_cmp:
            # The data is already committed, but an earlier push may have failed: push it now,
            # otherwise the commit would sit on this machine until the numbers change again.
            if not dry_run and _unpushed_commits(repo, branch) > 0:
                err = _push(repo, branch)
                if err:
                    return _error(err)
                print(json.dumps({"status": "pushed", "commit": _head(repo), "file": file_rel,
                                  "period": _week_key(doc), "pending": True}))
                return 0
            print(json.dumps({"status": "unchanged"}))
            return 0

    if dry_run:
        payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
        sys.stdout.write(payload)
        return 0

    # 4. Write file: 2 spaces indent, trailing newline
    target_dir = os.path.dirname(target_path)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    payload = json.dumps(doc, ensure_ascii=False, indent=2) + "\n"
    with open(target_path, "w", encoding="utf-8") as f:
        f.write(payload)

    # 5. git -C PATH add -- <file> && commit -m "..." -- <file>
    week_key = _week_key(doc)

    res = subprocess.run(["git", "-C", repo, "add", "--", file_rel],
                         capture_output=True, text=True, check=False)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        return _error("git add failed: %s" % err)

    commit_msg = "chore: update AI token usage (%s)" % week_key
    res = subprocess.run(["git", "-C", repo, "commit", "-m", commit_msg, "--", file_rel],
                         capture_output=True, text=True, check=False)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        return _error("git commit failed: %s" % err)

    # 6. git -C PATH push origin <branch> with 1 retry
    err = _push(repo, branch)
    if err:
        return _error(err)
    commit_sha = _head(repo)

    # 7. Output success JSON
    output = {
        "status": "pushed",
        "commit": commit_sha,
        "file": file_rel,
        "period": week_key,
    }
    print(json.dumps(output))
    return 0
