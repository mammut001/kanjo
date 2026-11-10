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
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote

# Directories that never become a project on their own (missing-path fallback).
_TEMP_PREFIXES = ("/tmp/", "/private/tmp/", "/var/folders/", "/private/var/folders/")
# "name.ext": treated as a file, so it is not itself checked for a .git entry
_FILE_LIKE = re.compile(r"[^.]\.[A-Za-z0-9]{1,10}$")

_CLEAN_CACHE: Dict[str, Optional[str]] = {}
_WINDOWS_ABS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def _is_subpath(p: str, prefix: str) -> bool:
    clean_prefix = prefix.rstrip("/\\")
    if p == clean_prefix:
        return True
    return p.startswith(clean_prefix + "/") or p.startswith(clean_prefix + "\\")


def _path_basename(path: str) -> str:
    p = path.rstrip("/\\")
    return p.split("/")[-1].split("\\")[-1]


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
        p = unquote(u[len("file://"):])
        if re.match(r"^/[A-Za-z]:", p):
            p = p[1:]
        return os.path.normpath(p)
    if u.startswith("/") or u.startswith("~") or u.startswith(".") or bool(_WINDOWS_ABS_PATH.match(u)):
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
        res = getattr(self, "_cached_path_missing", None)
        if res is not None:
            return res
        if not self.paths:
            res = self.path_missing_hint
        else:
            res = not any(os.path.exists(self.fs_root + p) for p in self.paths)
        self._cached_path_missing = res
        return res

    @property
    def local_paths(self) -> List[str]:
        return list(self.paths)

    def add_path(self, path: str) -> None:
        if path:
            if path not in self.paths:
                self.paths.add(path)
                self._cached_path_missing = None


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


def _session_worktree_sig(s) -> str:
    tps = getattr(s, "tool_paths", ())
    return "%s:%s:%d:%s" % (
        getattr(s, "cwd", "") or "",
        len(getattr(s, "messages", ())),
        len(tps),
        getattr(s, "ended", 0.0),
    )


class Resolver:
    """Maps arbitrary paths found in logs to projects. All lookups are memoized."""

    def __init__(self, aliases: Optional[Dict[str, List[str]]] = None, home: Optional[str] = None,
                 fs_root: Optional[str] = None, repo_cache=None, worktree_cache=None):
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
        self._worktree_prefix_cache: Dict[str, Optional[Tuple[str, str]]] = {}
        self._hint_prefix_cache: Dict[str, Optional[Tuple[str, str]]] = {}
        self._fast_resolve_cache: Dict[Tuple[str, bool], Optional[Project]] = {}
        self._alias_of: Dict[str, str] = {}       # member id/path -> canonical id
        self.repo_cache = repo_cache
        self.worktree_cache = worktree_cache
        self._repo_dict_projects: Dict[Tuple, Optional[Project]] = {}
        self._hint_paths_added: Optional[List[Tuple[str, str]]] = None
        for canonical, members in (aliases or {}).items():
            for member in members or []:
                self._alias_of[self._alias_key(member)] = canonical

    @property
    def _projects(self) -> Dict[str, Project]:
        return self.projects

    # ---- aliases ---------------------------------------------------------
    @staticmethod
    def _alias_key(value: str) -> str:
        value = (value or "").strip()
        if value.startswith("/") or value.startswith("~") or bool(_WINDOWS_ABS_PATH.match(value)):
            return os.path.normpath(os.path.expanduser(value))
        return normalize_remote(value) or value.lower()

    def canonical_id(self, pid: str, paths=()) -> str:
        if pid in self._alias_of:
            return self._alias_of[pid]
        for p in paths:
            for key, canonical in self._alias_of.items():
                if (key.startswith("/") or bool(_WINDOWS_ABS_PATH.match(key))) and (p == key or _is_subpath(p, key)):
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
        if not (self._exists_cached(os.path.join(common, "HEAD")) or
                self._exists_cached(os.path.join(common, "config")) or
                self._exists_cached(os.path.join(dotgit, "HEAD")) or
                self._exists_cached(os.path.join(dotgit, "config"))):
            return None
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
    def _project_for_repo(self, info: RepoInfo) -> Optional[Project]:
        if not self.fs_root and info.remote_url is None and info.outer is None and not self._aliased(info):
            roots = [r for r in (info.main_root, info.root) if r]
            if any((r.rstrip("/") + "/").startswith(_TEMP_PREFIXES) for r in roots):
                return None
        if info.outer is not None and not self._aliased(info):
            # remote-less repo nested in another repo: the outer repo's project
            # (ATTRIBUTION.md 2.2); user aliases on the inner path still win
            project = self._project_for_repo(info.outer)
            if project is not None:
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
            if (key.startswith("/") or bool(_WINDOWS_ABS_PATH.match(key))) and any(p == key or _is_subpath(p, key) for p in own):
                outer_paths = (info.outer.root, info.outer.main_root) if info.outer else ()
                if not any(o == key or _is_subpath(o, key) for o in outer_paths):
                    return True
        return False

    def _get_project(self, pid, name, remote, paths, missing=False) -> Project:
        canonical = self.canonical_id(pid, paths)
        project = self.projects.get(canonical)
        if project is None:
            if canonical != pid:
                is_path = canonical.startswith("/") or bool(_WINDOWS_ABS_PATH.match(canonical))
                name = _path_basename(canonical) if is_path else (canonical.rstrip("/").split("/")[-1])
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
        added = []
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
                added.append(target)
                alt = _private_alias(target)
                if alt != target:
                    added.append(alt)
        if added and self._worktree_prefix_cache:
            for wt in added:
                to_del = [k for k in self._worktree_prefix_cache if k == wt or k.startswith(wt + "/")]
                for k in to_del:
                    del self._worktree_prefix_cache[k]

    def add_remote_hint(self, path: str, remote_url: str) -> None:
        """A log recorded that ``path`` was a checkout of ``remote_url``
        (Antigravity trajectory metadata, Codex session_meta.git). Used only
        when the path cannot be resolved from the filesystem (deleted
        worktrees and clones)."""
        path = self.clean(path)
        if path and remote_url and normalize_remote(remote_url):
            self._hints[path] = remote_url
            self._hints.setdefault(_private_alias(path), remote_url)
            self._hint_prefix_cache.clear()

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
            if re.match(r"^/[A-Za-z]:", p):
                p = p[1:]
        if p.startswith("~"):
            p = os.path.expanduser(p)
        is_abs = p.startswith("/") or bool(_WINDOWS_ABS_PATH.match(p))
        if not is_abs:
            _CLEAN_CACHE[path] = None
            return None
        p = p.rstrip(".,:;")
        if "\\" in p:
            res = os.path.normpath(p) if p else None
        elif (len(p) > 1 and not p.endswith("/") and "//" not in p
                and "/./" not in p and "/../" not in p and not p.endswith("/.") and not p.endswith("/..")):
            res = p
        else:
            res = os.path.normpath(p) if p else None
        _CLEAN_CACHE[path] = res
        return res

    def _lookup_prefix_cached(self, path: str, table: Dict[str, str]):
        if not table:
            return None
        cache = self._worktree_prefix_cache if table is self._worktrees else self._hint_prefix_cache
        if path in cache:
            return cache[path]
        res = self._lookup_prefix(path, table)
        cache[path] = res
        return res

    def resolve(self, path: str, allow_missing_fallback: bool = False) -> Optional[Project]:
        """Path -> Project or None (not a project). ``allow_missing_fallback``
        marks ``path`` as a working directory: it is checked for ``.git`` even
        if it looks like a file name, and a deleted directory becomes its own
        project (ATTRIBUTION.md section 9)."""
        if not path:
            return None
        fast_key = (path, allow_missing_fallback)
        if fast_key in self._fast_resolve_cache:
            return self._fast_resolve_cache[fast_key]

        p = self.clean(path)
        if not p:
            self._fast_resolve_cache[fast_key] = None
            return None
        cache_key = p + ("\0m" if allow_missing_fallback else "")
        if cache_key in self._resolve_cache:
            pid = self._resolve_cache[cache_key]
            res = self.projects.get(pid) if pid else None
            self._fast_resolve_cache[fast_key] = res
            return res

        if self.repo_cache is not None:
            hit, cached = self.repo_cache.get(p, self.fs_root)
            if not hit:
                alt = _private_alias(p)
                if alt != p:
                    hit, cached = self.repo_cache.get(alt, self.fs_root)
            if hit:
                if cached is not None:
                    repo_key = (cached.get("root"), cached.get("main_root"), cached.get("remote"))
                    if repo_key in self._repo_dict_projects:
                        project = self._repo_dict_projects[repo_key]
                    else:
                        info = _load_repo(cached)
                        project = self._project_for_repo(info)
                        self._repo_dict_projects[repo_key] = project
                    self._resolve_cache[cache_key] = project.id if project else None
                    self._fast_resolve_cache[fast_key] = project
                    return project
                elif not allow_missing_fallback:
                    if not self.hints_enabled:
                        return None
                    if self._worktrees:
                        alt = _private_alias(p)
                        if self._lookup_prefix_cached(p, self._worktrees) or (alt != p and self._lookup_prefix_cached(alt, self._worktrees)):
                            project = self._resolve_uncached(p, allow_missing_fallback)
                            self._resolve_cache[cache_key] = project.id if project else None
                            self._fast_resolve_cache[fast_key] = project
                            return project
                    if self.hints_enabled and self._hints:
                        alt = _private_alias(p)
                        if self._lookup_prefix_cached(p, self._hints) or (alt != p and self._lookup_prefix_cached(alt, self._hints)):
                            project = self._resolve_uncached(p, allow_missing_fallback)
                            self._resolve_cache[cache_key] = project.id if project else None
                            self._fast_resolve_cache[fast_key] = project
                            return project
                    self._resolve_cache[cache_key] = None
                    self._fast_resolve_cache[fast_key] = None
                    return None

        project = self._resolve_uncached(p, allow_missing_fallback)
        self._resolve_cache[cache_key] = project.id if project else None
        self._fast_resolve_cache[fast_key] = project
        return project

    def _resolve_uncached(self, p: str, allow_missing_fallback: bool) -> Optional[Project]:
        alt = _private_alias(p)
        # 1. nearest .git above the path
        info = self._repo_for_path(p, allow_missing_fallback)
        if info is None and alt != p:
            info = self._repo_for_path(alt, allow_missing_fallback)
        if info is not None:
            proj = self._project_for_repo(info)
            if proj is not None:
                return proj
        # 2. registered worktrees (git worktree list), even if the directory is gone
        for candidate in (p, alt):
            found = self._lookup_prefix_cached(candidate, self._worktrees)
            if found:
                return self.projects.get(found[1])
        # 3. remote recorded in the logs for this checkout. Only folds a deleted
        #    checkout into a project that still exists on disk; a project known
        #    only from logs stays path-identified (CONTRACT.md: path_missing
        #    projects have a path id and no remote).
        if self.hints_enabled:
            for candidate in (p, alt):
                found = self._lookup_prefix_cached(candidate, self._hints)
                if found:
                    hint_path, hint = found
                    project = self.projects.get(self.canonical_id(normalize_remote(hint) or ""))
                    if project is not None and not project.path_missing:
                        project.paths.add(hint_path)
                        if self._hint_paths_added is not None:
                            self._hint_paths_added.append((project.id, hint_path))
                        return project
                    break
        # 4. deleted project directory (cwd only): the path itself is the identity
        if allow_missing_fallback and self._missing_ok(p) and not self._exists_cached(p):
            return self._get_project(p, _path_basename(p) or p, None, [p], missing=True)
        return None

    def _missing_ok(self, p: str) -> bool:
        if p == self.home or not _is_subpath(p, self.home):
            return False
        if any((p + "/").startswith(t) or (p + "\\").startswith(t) for t in _TEMP_PREFIXES):
            return False
        rel = os.path.relpath(p, self.home)
        first_comp = rel.replace("\\", "/").split("/")[0]
        if first_comp.startswith("."):
            return False  # agent state dirs (~/.claude, ~/.codex, ~/.gemini ...)
        return True

    @staticmethod
    def _lookup_prefix(path: str, table: Dict[str, str]):
        """Longest whole-component prefix of ``path`` that is a key of ``table``."""
        if not table or path is None:
            return None
        if path in table:
            return path, table[path]
        idx = len(path)
        while True:
            idx = max(path.rfind("/", 0, idx), path.rfind("\\", 0, idx))
            if idx == -1:
                break
            cand = path[:idx]
            cand_slash = path[:idx + 1]
            if cand_slash in table:
                return cand_slash, table[cand_slash]
            if cand and cand in table:
                return cand, table[cand]
        if (path.startswith("/") or bool(_WINDOWS_ABS_PATH.match(path))) and "" in table:
            return "", table[""]
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
            self._fast_resolve_cache = {k: v for k, v in self._fast_resolve_cache.items() if v is not None}
            self._hint_prefix_cache.clear()

    def infer_deleted_worktrees(self, sessions: Iterable) -> None:
        """Folds deleted temporary worktrees (Pi / Claude) back into their main repository.
        Uses relative file paths touched by tool calls (Signal A) and cross-session
        references in parent sessions' tool calls (Signal B)."""
        session_list = list(sessions)

        # 1 & 2: Pre-resolve session cwds and collect known remote projects
        session_pid: Dict[int, str] = {}
        clean_cwds: Dict[int, str] = {}
        sessions_by_id = {}
        for s in session_list:
            if hasattr(s, "id"):
                sessions_by_id[s.id] = s
            cwd = getattr(s, "cwd", None)
            if cwd:
                clean_cwd = self.clean(cwd)
                if clean_cwd:
                    clean_cwds[id(s)] = clean_cwd
                    proj = self.resolve(clean_cwd, allow_missing_fallback=False)
                    if proj is not None and not proj.path_missing and not (proj.remote and proj.remote.endswith(".bundle")):
                        session_pid[id(s)] = proj.id

        session_sigs: Dict[str, str] = {}

        def get_sig(s_id: str) -> Optional[str]:
            if s_id not in session_sigs:
                s = sessions_by_id.get(s_id)
                if s is not None:
                    session_sigs[s_id] = _session_worktree_sig(s)
            return session_sigs.get(s_id)

        class LazySessionSigs(dict):
            def __getitem__(self, s_id):
                sig = get_sig(s_id)
                if sig is None:
                    raise KeyError(s_id)
                return sig
            def get(self, s_id, default=None):
                sig = get_sig(s_id)
                return sig if sig is not None else default
            def __contains__(self, s_id):
                return s_id in sessions_by_id

        lazy_sigs = LazySessionSigs()

        known_projects: Dict[str, List[str]] = {}
        for proj in self.projects.values():
            if proj.remote and not proj.path_missing and not proj.remote.endswith(".bundle"):
                roots = [r for r in proj.local_paths if self._exists_cached(r)]
                if roots:
                    known_projects[proj.id] = roots

        if not known_projects:
            return

        # Lazy tool paths and parent sessions
        s_tool_paths: Dict[int, List[str]] = {}

        def get_session_tool_paths(s) -> List[str]:
            sid = id(s)
            if sid not in s_tool_paths:
                paths = []
                for tp in self._iter_tool_paths(s):
                    clean_tp = self.clean(tp)
                    if clean_tp:
                        paths.append(os.path.normpath(clean_tp))
                s_tool_paths[sid] = paths
            return s_tool_paths[sid]

        parent_sessions_info: Optional[List[Tuple[object, str, List[str]]]] = None

        def get_parent_sessions_info() -> List[Tuple[object, str, List[str]]]:
            nonlocal parent_sessions_info
            if parent_sessions_info is None:
                parent_sessions_info = []
                for parent_s in session_list:
                    parent_pid = session_pid.get(id(parent_s))
                    if parent_pid and parent_pid in known_projects:
                        tps = get_session_tool_paths(parent_s)
                        if tps:
                            parent_sessions_info.append((parent_s, parent_pid, tps))
            return parent_sessions_info

        # Fold local .bundle clone workspaces into their matching remote repo
        for bproj in list(self.projects.values()):
            if (bproj.remote and
                    isinstance(bproj.remote, str) and
                    (bproj.remote.startswith("/") or bool(_WINDOWS_ABS_PATH.match(bproj.remote))) and
                    bproj.remote.endswith(".bundle") and
                    self._alias_key(bproj.id) not in self._alias_of and
                    bproj.id not in self._alias_of):

                cached_bundle = None
                if self.worktree_cache is not None:
                    cached_bundle = self.worktree_cache.get_bundle(bproj.id, lazy_sigs, known_projects)

                if cached_bundle is not None:
                    best_pid, bpaths = cached_bundle
                    alias_key = self._alias_key(bproj.id)
                    self._alias_of[alias_key] = best_pid
                    self._alias_of[bproj.id] = best_pid
                    target_proj = self.projects.get(best_pid)
                    if target_proj is not None:
                        for p in (set(bproj.paths) | set(bpaths)):
                            target_proj.add_path(p)
                            self._worktrees[p] = best_pid
                            alt_p = _private_alias(p)
                            if alt_p != p:
                                self._worktrees[alt_p] = best_pid
                    if bproj.id in self.projects:
                        del self.projects[bproj.id]
                    self._worktree_prefix_cache.clear()
                    self._resolve_cache.clear()
                    self._fast_resolve_cache.clear()
                    self._repo_dict_projects.clear()
                    continue

                distinct_rels = set()
                bproj_relevant_sigs: Dict[str, str] = {}
                # 1. From sessions under bproj paths
                for s in session_list:
                    s_cwd = clean_cwds.get(id(s))
                    s_cwds = [s_cwd] if s_cwd else []
                    tps = get_session_tool_paths(s)
                    falls_under = False
                    for r in bproj.local_paths:
                        r_prefix = r.rstrip("/") + "/"
                        if any(c and (c == r or c.startswith(r_prefix)) for c in s_cwds):
                            falls_under = True
                            break
                        for clean_tp in tps:
                            if clean_tp == r or clean_tp.startswith(r_prefix):
                                falls_under = True
                                break
                    if falls_under:
                        if hasattr(s, "id"):
                            bproj_relevant_sigs[s.id] = lazy_sigs[s.id]
                        for clean_tp in tps:
                            for r in bproj.local_paths:
                                r_prefix = r.rstrip("/") + "/"
                                if clean_tp.startswith(r_prefix):
                                    rel = clean_tp[len(r_prefix):]
                                    first_comp = rel.split("/", 1)[0]
                                    if "/" in rel and first_comp not in (".git", "node_modules"):
                                        distinct_rels.add(rel)

                # 2. From on-disk files in bproj roots
                for r in bproj.local_paths:
                    fs_r = self._fs(r)
                    if self._exists_cached(r) and os.path.isdir(fs_r):
                        try:
                            entries = os.listdir(fs_r)
                        except OSError:
                            entries = []
                        if "package.json" in entries:
                            distinct_rels.add("package.json")
                        for entry in entries:
                            if entry in (".git", "node_modules", "dist", "build", ".next", ".turbo"):
                                continue
                            sub_path = os.path.join(fs_r, entry)
                            if os.path.isdir(sub_path):
                                try:
                                    sub_entries = os.listdir(sub_path)
                                except OSError:
                                    sub_entries = []
                                for f in sub_entries[:15]:
                                    if not f.startswith("."):
                                        distinct_rels.add(os.path.join(entry, f))

                # Match against known_projects
                matches: Dict[str, int] = {}
                for pid, roots in known_projects.items():
                    count = 0
                    for rel in distinct_rels:
                        if any(self._exists_cached(os.path.join(root, rel)) for root in roots):
                            count += 1
                    if count > 0:
                        matches[pid] = count

                if matches:
                    max_count = max(matches.values())
                    top_pids = sorted([pid for pid, cnt in matches.items() if cnt == max_count])
                    best_pid = top_pids[0]

                    alias_key = self._alias_key(bproj.id)
                    self._alias_of[alias_key] = best_pid
                    self._alias_of[bproj.id] = best_pid

                    target_proj = self.projects.get(best_pid)
                    if target_proj is not None:
                        for p in bproj.paths:
                            target_proj.add_path(p)
                            self._worktrees[p] = best_pid
                            alt_p = _private_alias(p)
                            if alt_p != p:
                                self._worktrees[alt_p] = best_pid

                    if bproj.id in self.projects:
                        del self.projects[bproj.id]

                    if self.worktree_cache is not None:
                        self.worktree_cache.put_bundle(bproj.id, best_pid, bproj.paths, bproj_relevant_sigs)

                    self._worktree_prefix_cache.clear()
                    self._resolve_cache.clear()
                    self._fast_resolve_cache.clear()
                    self._repo_dict_projects.clear()

        # 3. Find candidate deleted cwd directories
        candidate_cwds = set()
        sessions_by_norm_cwd = defaultdict(list)
        for s in session_list:
            clean = clean_cwds.get(id(s))
            if clean:
                norm = os.path.normpath(clean)
                candidate_cwds.add(norm)
                sessions_by_norm_cwd[norm].append(s)

        candidates = [
            d for d in candidate_cwds
            if not self._exists_cached(d)
            and self.resolve(d, allow_missing_fallback=False) is None
            and self._missing_ok(d)
        ]
        candidates.sort(key=len)

        for d in candidates:
            if self.resolve(d, allow_missing_fallback=False) is not None:
                continue

            if self.worktree_cache is not None:
                cached_pid = self.worktree_cache.get_worktree(d, lazy_sigs, known_projects, self._exists_cached)
                if cached_pid is not None:
                    if cached_pid == "":
                        continue
                    if cached_pid in self.projects:
                        self._worktrees[d] = cached_pid
                        alt_d = _private_alias(d)
                        if alt_d != d:
                            self._worktrees[alt_d] = cached_pid
                        self.projects[cached_pid].add_path(d)
                        self._worktree_prefix_cache.clear()
                        self._resolve_cache.clear()
                        self._fast_resolve_cache.clear()
                        self._repo_dict_projects.clear()
                        known_projects[cached_pid].append(d)
                        continue

            # Gather sessions whose normalized cwd == d or inside d + "/"
            d_slash = d + "/"
            d_sessions = []
            for norm_cwd, slist in sessions_by_norm_cwd.items():
                if norm_cwd == d or norm_cwd.startswith(d_slash):
                    d_sessions.extend(slist)

            d_relevant_sigs: Dict[str, str] = {}
            for s in d_sessions:
                if hasattr(s, "id"):
                    d_relevant_sigs[s.id] = lazy_sigs[s.id]

            # Signal A: relative file paths matching against existing repos
            distinct_rels = set()
            for s in d_sessions:
                for norm_tp in get_session_tool_paths(s):
                    if norm_tp.startswith(d_slash):
                        rel = norm_tp[len(d_slash):]
                        first_comp = rel.split("/", 1)[0]
                        if "/" in rel and first_comp not in (".git", "node_modules"):
                            distinct_rels.add(rel)

            matches: Dict[str, int] = {}
            for pid, roots in known_projects.items():
                count = 0
                for rel in distinct_rels:
                    if any(self._exists_cached(os.path.join(root, rel)) for root in roots):
                        count += 1
                if count > 0:
                    matches[pid] = count

            best_pid = None
            if matches:
                max_count = max(matches.values())
                top_pids = sorted([pid for pid, cnt in matches.items() if cnt == max_count])
                d_parent = os.path.dirname(d)
                best_pid = max(
                    top_pids,
                    key=lambda pid: 1 if any(os.path.dirname(r) == d_parent for r in known_projects[pid]) else 0,
                )

            # Signal B: parent session / tool_paths cross-reference
            if best_pid is None:
                parent_refs: Counter = Counter()
                matching_parents: List[Tuple[object, str]] = []
                for parent_s, parent_pid, tps in get_parent_sessions_info():
                    matched = False
                    for norm_tp in tps:
                        if norm_tp == d or norm_tp.startswith(d_slash):
                            parent_refs[parent_pid] += 1
                            matched = True
                    if matched:
                        matching_parents.append((parent_s, parent_pid))
                if parent_refs:
                    max_refs = max(parent_refs.values())
                    top_parent_pids = sorted([pid for pid, cnt in parent_refs.items() if cnt == max_refs])
                    d_parent = os.path.dirname(d)
                    best_pid = max(
                        top_parent_pids,
                        key=lambda pid: 1 if any(os.path.dirname(r) == d_parent for r in known_projects[pid]) else 0,
                    )
                    for parent_s, p_pid in matching_parents:
                        if p_pid == best_pid and hasattr(parent_s, "id"):
                            d_relevant_sigs[parent_s.id] = lazy_sigs[parent_s.id]

            if best_pid is not None and best_pid in self.projects:
                self._worktrees[d] = best_pid
                alt_d = _private_alias(d)
                if alt_d != d:
                    self._worktrees[alt_d] = best_pid
                self.projects[best_pid].add_path(d)
                if self.worktree_cache is not None:
                    self.worktree_cache.put_worktree(d, best_pid, d_relevant_sigs)
                self._worktree_prefix_cache.clear()
                self._resolve_cache.clear()
                self._fast_resolve_cache.clear()
                self._repo_dict_projects.clear()
                known_projects[best_pid].append(d)
            elif self.worktree_cache is not None:
                self.worktree_cache.put_worktree(d, None, d_relevant_sigs)
        self._repo_dict_projects.clear()

    @staticmethod
    def _iter_tool_paths(session) -> Iterable[str]:
        for call in getattr(session, "tool_paths", ()):
            if isinstance(call, (list, tuple, set)):
                for p in call:
                    if isinstance(p, str):
                        yield p
            elif isinstance(call, str):
                yield call

    def project(self, pid: str) -> Optional[Project]:
        return self.projects.get(pid)

    def ensure_project(self, pid: str) -> Project:
        """Project named directly by id (config overrides / aliases)."""
        pid = self.canonical_id(pid)
        if pid in self.projects:
            return self.projects[pid]
        is_path = pid.startswith("/") or bool(_WINDOWS_ABS_PATH.match(pid))
        name = _path_basename(pid) if is_path else pid.rstrip("/").split("/")[-1]
        return self._get_project(pid, name or pid, None if is_path else pid,
                                 [pid] if is_path else [])


# ---- scratchpad paths ------------------------------------------------------
_SCRATCH_RE = re.compile(r"^(?:/private)?/tmp/claude-\d+/(-[^/]+)(?:/|$)")
_CLAUDE_PROJECT_DIR_RE = re.compile(r"/\.claude/projects/(-[^/]+)(?:/|$)")


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
        if m:
            return m.group(1)
        m = _CLAUDE_PROJECT_DIR_RE.search(path)
        if m:
            return m.group(1)
        return None

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
