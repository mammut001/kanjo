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


def cmd_publish_usage(args) -> int:
    repo = os.path.abspath(args.repo)
    file_rel = args.file
    branch = args.branch
    dry_run = getattr(args, "dry_run", False)

    if not os.path.isdir(repo):
        return _error("repository directory does not exist: %s" % repo)

    # 1. Check PATH is a git repository
    res = subprocess.run(["git", "-C", repo, "rev-parse", "--is-inside-work-tree"],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    if res.returncode != 0 or res.stdout.strip() != "true":
        return _error("%s is not a git repository" % repo)

    # Check current branch equals required branch
    res = subprocess.run(["git", "-C", repo, "branch", "--show-current"],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    current_branch = res.stdout.strip()
    if current_branch != branch:
        return _error("current branch '%s' does not match required branch '%s'" % (current_branch, branch))

    # 2. git -C PATH pull --ff-only origin <branch>
    if not dry_run:
        res = subprocess.run(["git", "-C", repo, "pull", "--ff-only", "origin", branch],
                             capture_output=True, text=True, encoding="utf-8", check=False)
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
    if doc.get("weeks"):
        week_key = doc["weeks"][-1]["period"]
    else:
        week_key = doc.get("all_time", {}).get("period", "all")

    res = subprocess.run(["git", "-C", repo, "add", "--", file_rel],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        return _error("git add failed: %s" % err)

    commit_msg = "chore: update AI token usage (%s)" % week_key
    res = subprocess.run(["git", "-C", repo, "commit", "-m", commit_msg, "--", file_rel],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    if res.returncode != 0:
        err = res.stderr.strip() or res.stdout.strip()
        return _error("git commit failed: %s" % err)

    res = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    commit_sha = res.stdout.strip()

    # 6. git -C PATH push origin <branch> with 1 retry
    res = subprocess.run(["git", "-C", repo, "push", "origin", branch],
                         capture_output=True, text=True, encoding="utf-8", check=False)
    if res.returncode != 0:
        rebase_res = subprocess.run(["git", "-C", repo, "pull", "--rebase", "origin", branch],
                                    capture_output=True, text=True, encoding="utf-8", check=False)
        if rebase_res.returncode != 0:
            err = rebase_res.stderr.strip() or rebase_res.stdout.strip()
            return _error("git pull --rebase failed: %s" % err)

        retry_res = subprocess.run(["git", "-C", repo, "push", "origin", branch],
                                   capture_output=True, text=True, encoding="utf-8", check=False)
        if retry_res.returncode != 0:
            err = retry_res.stderr.strip() or retry_res.stdout.strip()
            return _error("git push retry failed: %s" % err)

        res = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"],
                             capture_output=True, text=True, encoding="utf-8", check=False)
        commit_sha = res.stdout.strip()

    # 7. Output success JSON
    output = {
        "status": "pushed",
        "commit": commit_sha,
        "file": file_rel,
        "period": week_key,
    }
    print(json.dumps(output))
    return 0
