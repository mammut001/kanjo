"""Path -> project identity (ATTRIBUTION.md section 2).

A project is identified by the normalized URL of its git remote (``origin``,
or the first remote when there is no origin). Worktrees are folded into their
main repository; several clones with the same remote are the same project.
A git repository without a remote that sits inside another git repository
(``FocusApp/Packages/FocusKit``) is folded into the enclosing repository's
project; one that is not nested is identified by the absolute path of its
(main) root directory.

Everything here reads files directly (``.git``, ``.git/config``,
``.git/worktrees/*/gitdir``) instead of running ``git``: it is faster, needs
no git binary, and still works for worktrees whose admin dir was pruned
(the ``.git`` file then points at a missing ``.../.git/worktrees/<name>``).
The registered worktree list read from ``.git/worktrees`` is what
``git worktree list`` prints.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from urllib.parse import unquote

# Directories that never become a project on their own (missing-path fallback).
_TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
# "name.ext": treated as a file, so it is not itself checked for a .git entry
_FILE_LIKE = re.compile(r"[^.]\.[A-Za-z0-9]{1,10}$")

_CLEAN_CACHE: Dict[str, Optional[str]] = {}


def clear_clean_cache() -> None:
    _CLEAN_CACHE.clear()


def _private_alias(path: str) -> str:
    """macOS spells the same directory /tmp/x and /private/tmp/x."""
    for short in ("/tmp", "/var", "/etc"):
        if path == short or path.startswith(short + "/"):
            return "/private" + path
        if path == "/private" + short or path.startswith("/private" + short + "/"):
            return path[len("/private"):]
    return path


def normalize_remote(url: str) -> Optional[str]:
    """``git@github.com:cclank/tokei.git`` / ``https://github.com/cclank/tokei(.git)``
    -> ``github.com/cclank/tokei``. Protocol, user name, ``.git`` suffix and
    trailing slashes are removed; host and path are lowercased."""
    if not url:
        return None
    u = url.strip()
    if not u:
        return None
    if u.startswith("file://"):
        return os.path.normpath(unquote(u[len("file://"):]))
    if u.startswith("/") or u.startswith("~") or u.startswith("."):
        return os.path.normpath(os.path.expanduser(u))
    m = re.match(r"^[A-Za-z][A-Za-z0-9+.\-]*://(.*)$", u)
    if m:
        rest = m.group(1)
        if "@" in rest.split("/", 1)[0]:
            rest = rest.split("@", 1)[1]
        host, _, path = rest.partition("/")
        host = host.split(":", 1)[0]  # drop port
    else:
        # scp-like syntax: [user@]host:path
        m = re.match(r"^(?:[^@/]+@)?([^:/]+):(.*)$", u)
        if not m:
            return None
        host, path = m.group(1), m.group(2)
    path = path.strip("/")
    while path.endswith("/"):
        path = path[:-1]
    if path.lower().endswith(".git"):
        path = path[:-4]
    path = path.strip("/")
    if not host:
        return None
    return (host + ("/" + path if path else "")).lower()


def _remote_display_name(url: str) -> Optional[str]:
    if not url:
        return None
    tail = re.split(r"[/:]", url.strip().rstrip("/"))[-1]
    if tail.lower().endswith(".git"):
        tail = tail[:-4]
    return tail or None


def parse_git_config_remotes(text: str) -> List[tuple]:
    """Return [(remote name, url)] in file order."""
    remotes = []
    current = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        sec = re.match(r'^\[\s*remote\s+"([^"]+)"\s*\]$', line)
        if sec:
            current = sec.group(1)
            continue
        if line.startswith("["):
            current = None
            continue
        if current is not None:
            kv = re.match(r"^url\s*=\s*(.+)$", line)
            if kv:
                value = kv.group(1).strip()
                if len(value) >= 2 and value[0] == value[-1] == '"':
                    value = value[1:-1]
                remotes.append((current, value))
    return remotes


def pick_remote(remotes: List[tuple]) -> Optional[str]:
    for name, url in remotes:
        if name == "origin":
            return url
    return remotes[0][1] if remotes else None


@dataclass
class Project:
    id: str
    name: str
    remote: Optional[str]
    paths: Set[str] = field(default_factory=set)
    path_missing_hint: bool = False
    fs_root: str = ""

    @property
    def path_missing(self) -> bool:
        if not self.paths:
            return self.path_missing_hint
        return not any(os.path.exists(self.fs_root + p) for p in self.paths)


@dataclass
class RepoInfo:
    root: str           # the working tree root that contains the path
    main_root: str      # main working tree root (worktrees -> main repo)
    common_dir: str     # shared .git dir
    remote_url: Optional[str]
    # enclosing repository, set only when this one has no remote (nested repo)
    outer: Optional["RepoInfo"] = None


def _dump_repo(info: Optional[RepoInfo]) -> Optional[dict]:
    if info is None:
        return None
    return {
        "root": info.root,
        "main_root": info.main_root,
        "common_dir": info.common_dir,
        "remote_url": info.remote_url,
        "outer": _dump_repo(info.outer),
    }


def _load_repo(d: Optional[dict]) -> Optional[RepoInfo]:
    if d is None:
        return None
    return RepoInfo(
        root=d["root"],
        main_root=d["main_root"],
        common_dir=d["common_dir"],
        remote_url=d.get("remote_url"),
        outer=_load_repo(d.get("outer")),
    )


class Resolver:
    """Maps arbitrary paths found in logs to projects. All lookups are memoized."""

    def __init__(self, aliases: Optional[Dict[str, List[str]]] = None, home: Optional[str] = None,
                 fs_root: Optional[str] = None, repo_cache=None):
        # fs_root: optional directory that stands in for "/" when touching the
        # filesystem (tests); every path in logs and output stays as logged.
        self.fs_root = (fs_root or "").rstrip("/")
        self.home = home or (os.path.realpath(os.path.expanduser("~")) if not self.fs_root else "/")
        self.projects: Dict[str, Project] = {}
        self._dir_repo: Dict[str, Optional[RepoInfo]] = {}
        self._exists: Dict[str, bool] = {}
        self._resolve_cache: Dict[str, Optional[str]] = {}
        self._worktrees: Dict[str, str] = {}      # worktree path -> project id
        self._seen_common: Set[str] = set()
        self._hints: Dict[str, str] = {}          # path prefix -> remote url from logs
        self.hints_enabled = True
        self._alias_of: Dict[str, str] = {}       # member id/path -> canonical id
        self.repo_cache = repo_cache
        for canonical, members in (aliases or {}).items():
            for member in members or []:
                self._alias_of[self._alias_key(member)] = canonical

    # ---- aliases ---------------------------------------------------------
    @staticmethod
    def _alias_key(value: str) -> str:
        value = (value or "").strip()
        if value.startswith("/") or value.startswith("~"):
            return os.path.normpath(os.path.expanduser(value))
        return normalize_remote(value) or value.lower()

    def canonical_id(self, pid: str, paths=()) -> str:
        if pid in self._alias_of:
            return self._alias_of[pid]
        for p in paths:
            for key, canonical in self._alias_of.items():
                if key.startswith("/") and (p == key or p.startswith(key.rstrip("/") + "/")):
                    return canonical
        return pid

    # ---- filesystem helpers ---------------------------------------------
    def _fs(self, path: str) -> str:
        return self.fs_root + path if self.fs_root else path

    def _real(self, path: str) -> str:
        if not self.fs_root:
            return os.path.realpath(path)
        real = os.path.realpath(self.fs_root + path)
        root = os.path.realpath(self.fs_root)
        return real[len(root):] or "/" if real.startswith(root) else os.path.normpath(path)

    def _exists_cached(self, path: str) -> bool:
        if path not in self._exists:
            self._exists[path] = os.path.exists(self._fs(path))
        return self._exists[path]

    def _repo_for_path(self, path: str, leaf_is_dir: bool) -> Optional[RepoInfo]:
        """Nearest enclosing git working tree, walking up from ``path`` (which
        may no longer exist). Every directory visited is memoized, so a scan
        costs about one ``lstat`` per distinct directory. The leaf itself is
        not checked for ``.git`` when it looks like a file name."""
        if path in self._dir_repo:
            return self._dir_repo[path]
        if self.repo_cache is not None:
            hit, cached = self.repo_cache.get(path, self.fs_root)
            if hit:
                info = _load_repo(cached)
                self._dir_repo[path] = info
                alt = _private_alias(path)
                if alt != path:
                    self._dir_repo[alt] = info
                return info

        leaf_checked = leaf_is_dir or not _FILE_LIKE.search(os.path.basename(path))
        chain = []
        cur = path
        result = None
        check = leaf_checked
        while True:
            if check and cur in self._dir_repo:
                result = self._dir_repo[cur]
                break
            if check and self.repo_cache is not None:
                hit, cached = self.repo_cache.get(cur, self.fs_root)
                if hit:
                    result = _load_repo(cached)
                    break
            if check:
                chain.append(cur)
                dotgit = os.path.join(cur, ".git")
                if os.path.lexists(self._fs(dotgit)):
                    info = self._read_repo(cur, dotgit)
                    if info is not None:
                        result = info
                        break
            check = True
            parent = os.path.dirname(cur)
            if parent == cur:
                break
            cur = parent

        dotgit = None
        sig = None
        dumped = None
        if result is not None:
            dotgit = os.path.join(result.root, ".git")
            stat_path = self._fs(dotgit)
            if self.repo_cache is not None and stat_path in self.repo_cache._stat_sig_cache:
                sig = self.repo_cache._stat_sig_cache[stat_path]
            else:
                try:
                    st = os.stat(stat_path)
                    sig = [st.st_mtime_ns, st.st_ino]
                    if self.repo_cache is not None:
                        self.repo_cache._stat_sig_cache[stat_path] = sig
                except OSError:
                    sig = None
            dumped = _dump_repo(result)

        for c in chain:
            self._dir_repo[c] = result
            alt_c = _private_alias(c)
            if alt_c != c:
                self._dir_repo[alt_c] = result
            if self.repo_cache is not None:
                if result is None:
                    self.repo_cache.put(c, None)
                    if alt_c != c:
                        self.repo_cache.put(alt_c, None)
                elif dotgit and sig:
                    self.repo_cache.put(c, dumped, dotgit, sig)
                    if alt_c != c:
                        self.repo_cache.put(alt_c, dumped, dotgit, sig)

        self._dir_repo[path] = result
        alt_p = _private_alias(path)
        if alt_p != path:
            self._dir_repo[alt_p] = result
        if self.repo_cache is not None:
            if result is None:
                self.repo_cache.put(path, None)
                if alt_p != path:
                    self.repo_cache.put(alt_p, None)
            elif dotgit and sig:
                self.repo_cache.put(path, dumped, dotgit, sig)
                if alt_p != path:
                    self.repo_cache.put(alt_p, dumped, dotgit, sig)

        return result

    def _read_repo(self, root: str, dotgit: str) -> Optional[RepoInfo]:
        if os.path.isdir(self._fs(dotgit)):
            gitdir = dotgit
        else:
            try:
                with open(self._fs(dotgit), "r", encoding="utf-8", errors="replace") as handle:
                    content = handle.read().strip()
            except OSError:
                return None
            if not content.startswith("gitdir:"):
                return None
            gitdir = content[len("gitdir:"):].strip()
            if not os.path.isabs(gitdir):
                gitdir = os.path.normpath(os.path.join(root, gitdir))
        common = gitdir
        commondir_file = os.path.join(gitdir, "commondir")
        if os.path.isfile(self._fs(commondir_file)):
            try:
                with open(self._fs(commondir_file), "r", encoding="utf-8") as handle:
                    rel = handle.read().strip()
                common = os.path.normpath(os.path.join(gitdir, rel))
            except OSError:
                pass
        elif os.path.basename(os.path.dirname(gitdir)) == "worktrees":
            # pruned worktree: admin dir is gone, but the layout tells us the main repo
            common = os.path.dirname(os.path.dirname(gitdir))
        main_root = os.path.dirname(common) if os.path.basename(common) == ".git" else root
        remote_url = None
        try:
            with open(self._fs(os.path.join(common, "config")), "r", encoding="utf-8", errors="replace") as handle:
                remote_url = pick_remote(parse_git_config_remotes(handle.read()))
        except OSError:
            pass
        info = RepoInfo(root=self._real(root), main_root=self._real(main_root),
                        common_dir=common, remote_url=remote_url)
        if not remote_url:
            info.outer = self._outer_repo(info)
        return info

    def _outer_repo(self, info: RepoInfo) -> Optional[RepoInfo]:
        """Nearest repository enclosing ``info``'s main root (searched from its
        parent directory up). The outer repo's own ``outer`` is filled in the
        same way, so a chain of remote-less repos ends at the first one with a
        remote or at the outermost one."""
        parent = os.path.dirname(info.main_root)
        if parent == info.main_root:
            return None
        outer = self._repo_for_path(parent, True)
        if outer is None or outer.common_dir == info.common_dir:
            return None
        return outer

    # ---- project registry ------------------------------------------------
    def _project_for_repo(self, info: RepoInfo) -> Project:
        if info.outer is not None and not self._aliased(info):
            # remote-less repo nested in another repo: the outer repo's project
            # (ATTRIBUTION.md 2.2); user aliases on the inner path still win
            project = self._project_for_repo(info.outer)
            for p in (info.root, info.main_root):
                if p:
                    project.paths.add(p)
            self._register_worktrees(info, project.id)
            return project
        remote = normalize_remote(info.remote_url) if info.remote_url else None
        if remote:
            pid, name, rem = remote, _remote_display_name(info.remote_url) or remote, remote
        else:
            pid, name, rem = info.main_root, os.path.basename(info.main_root) or info.main_root, None
        project = self._get_project(pid, name, rem, [info.root, info.main_root])
        self._register_worktrees(info, project.id)
        return project

    def _aliased(self, info: RepoInfo) -> bool:
        """The user aliased this repo's own path (not merely a parent of it)."""
        own = (info.root, info.main_root)
        for key in self._alias_of:
            if key.startswith("/") and any(p == key or p.startswith(key.rstrip("/") + "/") for p in own):
                outer_paths = (info.outer.root, info.outer.main_root) if info.outer else ()
                if not any(o == key or o.startswith(key.rstrip("/") + "/") for o in outer_paths):
                    return True
        return False

    def _get_project(self, pid, name, remote, paths, missing=False) -> Project:
        canonical = self.canonical_id(pid, paths)
        project = self.projects.get(canonical)
        if project is None:
            if canonical != pid:
                is_path = canonical.startswith("/")
                name = os.path.basename(canonical) if is_path else (canonical.rstrip("/").split("/")[-1])
                remote = None if is_path else canonical
            project = Project(id=canonical, name=name, remote=remote, path_missing_hint=missing,
                              fs_root=self.fs_root)
            self.projects[canonical] = project
        for p in paths:
            if p:
                project.paths.add(p)
        return project

    def _register_worktrees(self, info: RepoInfo, pid: str) -> None:
        if info.common_dir in self._seen_common:
            return
        self._seen_common.add(info.common_dir)
        wt_root = os.path.join(info.common_dir, "worktrees")
        try:
            names = os.listdir(self._fs(wt_root))
        except OSError:
            return
        for name in names:
            try:
                with open(self._fs(os.path.join(wt_root, name, "gitdir")), "r", encoding="utf-8") as handle:
                    target = handle.read().strip()
            except OSError:
                continue
            if target.endswith("/.git"):
                target = target[:-5]
            if target:
                target = os.path.normpath(target)
                self._worktrees[target] = pid
                self._worktrees[_private_alias(target)] = pid

    def add_remote_hint(self, path: str, remote_url: str) -> None:
        """A log recorded that ``path`` was a checkout of ``remote_url``
        (Antigravity trajectory metadata, Codex session_meta.git). Used only
        when the path cannot be resolved from the filesystem (deleted
        worktrees and clones)."""
        path = self.clean(path)
        if path and remote_url and normalize_remote(remote_url):
            self._hints[path] = remote_url
            self._hints.setdefault(_private_alias(path), remote_url)

    # ---- public API ------------------------------------------------------
    @staticmethod
    def clean(path: str) -> Optional[str]:
        try:
            return _CLEAN_CACHE[path]
        except KeyError:
            pass
        except TypeError:
            return None
        if not path or not isinstance(path, str):
            _CLEAN_CACHE[path] = None
            return None
        p = path.strip()
        if p.startswith("file://"):
            p = unquote(p[len("file://"):])
        if p.startswith("~"):
            p = os.path.expanduser(p)
        if not p.startswith("/"):
            _CLEAN_CACHE[path] = None
            return None
        p = p.rstrip(".,:;")
        if (len(p) > 1 and not p.endswith("/") and "//" not in p
                and "/./" not in p and "/../" not in p and not p.endswith("/.") and not p.endswith("/..")):
            res = p
        else:
            res = os.path.normpath(p) if p else None
        _CLEAN_CACHE[path] = res
        return res

    def resolve(self, path: str, allow_missing_fallback: bool = False) -> Optional[Project]:
        """Path -> Project or None (not a project). ``allow_missing_fallback``
        marks ``path`` as a working directory: it is checked for ``.git`` even
        if it looks like a file name, and a deleted directory becomes its own
        project (ATTRIBUTION.md section 9)."""
        p = self.clean(path)
        if not p:
            return None
        cache_key = p + ("\0m" if allow_missing_fallback else "")
        if cache_key in self._resolve_cache:
            pid = self._resolve_cache[cache_key]
            return self.projects.get(pid) if pid else None
        project = self._resolve_uncached(p, allow_missing_fallback)
        self._resolve_cache[cache_key] = project.id if project else None
        return project

    def _resolve_uncached(self, p: str, allow_missing_fallback: bool) -> Optional[Project]:
        alt = _private_alias(p)
        # 1. nearest .git above the path
        info = self._repo_for_path(p, allow_missing_fallback)
        if info is None and alt != p:
            info = self._repo_for_path(alt, allow_missing_fallback)
        if info is not None:
            return self._project_for_repo(info)
        # 2. registered worktrees (git worktree list), even if the directory is gone
        for candidate in (p, alt):
            found = self._lookup_prefix(candidate, self._worktrees)
            if found:
                return self.projects.get(found[1])
        # 3. remote recorded in the logs for this checkout. Only folds a deleted
        #    checkout into a project that still exists on disk; a project known
        #    only from logs stays path-identified (CONTRACT.md: path_missing
        #    projects have a path id and no remote).
        if self.hints_enabled:
            for candidate in (p, alt):
                found = self._lookup_prefix(candidate, self._hints)
                if found:
                    hint_path, hint = found
                    project = self.projects.get(self.canonical_id(normalize_remote(hint) or ""))
                    if project is not None and not project.path_missing:
                        project.paths.add(hint_path)
                        return project
                    break
        # 4. deleted project directory (cwd only): the path itself is the identity
        if allow_missing_fallback and self._missing_ok(p) and not self._exists_cached(p):
            return self._get_project(p, os.path.basename(p) or p, None, [p], missing=True)
        return None

    def _missing_ok(self, p: str) -> bool:
        if p == self.home or not p.startswith(self.home + "/"):
            return False
        if any((p + "/").startswith(t) for t in _TEMP_PREFIXES):
            return False
        rel = os.path.relpath(p, self.home)
        if rel.split("/")[0].startswith("."):
            return False  # agent state dirs (~/.claude, ~/.codex, ~/.gemini ...)
        return True

    @staticmethod
    def _lookup_prefix(path: str, table: Dict[str, str]):
        """Longest whole-component prefix of ``path`` that is a key of ``table``."""
        if not table:
            return None
        best_k = None
        for k in table:
            if path == k or (path.startswith(k) and (k.endswith("/") or path[len(k)] == "/")):
                if best_k is None or len(k) > len(best_k):
                    best_k = k
        if best_k is not None:
            return best_k, table[best_k]
        return None

    def prewarm(self, paths) -> None:
        """Discover every repository reachable from ``paths`` from the
        filesystem alone, so that log-recorded remotes (step 3) can be matched
        independently of the order sessions are processed in."""
        self.hints_enabled = False
        seen = set()
        try:
            for path in paths:
                if path not in seen:
                    seen.add(path)
                    self.resolve(path)
        finally:
            self.hints_enabled = True
            # Only invalidate entries that resolved to None, because they might
            # now resolve using hints (hints were disabled during prewarm).
            # Entries that already resolved to a project will never change.
            self._resolve_cache = {k: v for k, v in self._resolve_cache.items() if v is not None}

    def project(self, pid: str) -> Optional[Project]:
        return self.projects.get(pid)

    def ensure_project(self, pid: str) -> Project:
        """Project named directly by id (config overrides / aliases)."""
        pid = self.canonical_id(pid)
        if pid in self.projects:
            return self.projects[pid]
        is_path = pid.startswith("/")
        name = os.path.basename(pid.rstrip("/")) if is_path else pid.rstrip("/").split("/")[-1]
        return self._get_project(pid, name or pid, None if is_path else pid,
                                 [pid] if is_path else [])


# ---- scratchpad paths ------------------------------------------------------
_SCRATCH_RE = re.compile(r"^(?:/private)?/tmp/claude-\d+/(-[^/]+)(?:/|$)")


def _encode_component(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", name)


class ScratchpadDecoder:
    """Claude Code scratchpads live in ``/tmp/claude-<uid>/<encoded cwd>/<session>/scratchpad``;
    the encoded cwd replaces every non-alphanumeric character with ``-``.
    Decoding is ambiguous (``tcf-canada`` vs ``tcf/canada``), so it walks the
    real filesystem to find the directory whose encoding matches."""

    def __init__(self, fs_root: Optional[str] = None):
        self.fs_root = (fs_root or "").rstrip("/")
        self._cache: Dict[str, Optional[str]] = {}

    @staticmethod
    def encoded_part(path: str) -> Optional[str]:
        if not path:
            return None
        m = _SCRATCH_RE.match(path)
        return m.group(1) if m else None

    def decode(self, encoded: str) -> Optional[str]:
        if encoded in self._cache:
            return self._cache[encoded]
        result = self._walk("/", encoded[1:], 0) if encoded.startswith("-") else None
        self._cache[encoded] = result
        return result

    def _walk(self, base: str, rest: str, depth: int) -> Optional[str]:
        if depth > 32:
            return None
        try:
            entries = os.listdir(self.fs_root + base)
        except OSError:
            return None
        # longer names first so ``tcf-canada`` wins over ``tcf``
        for name in sorted(entries, key=len, reverse=True):
            enc = _encode_component(name)
            if not enc:
                continue
            full = os.path.join(base, name)
            if rest == enc:
                if os.path.isdir(self.fs_root + full):
                    return full
            elif rest.startswith(enc + "-") and os.path.isdir(self.fs_root + full):
                found = self._walk(full, rest[len(enc) + 1:], depth + 1)
                if found:
                    return found
        return None

    def project_path(self, path: str) -> Optional[str]:
        enc = self.encoded_part(path)
        return self.decode(enc) if enc else None
