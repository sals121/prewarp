"""Path checks for file names that come from an LLM (MCP clients, the Claude agent).

A prompt-injected model could otherwise ask the solver to open any file on the machine, or a
UNC path (``\\\\host\\share\\x.stl``) that makes Windows authenticate to a remote host and hand
it the user's NTLM hash. Only existing local ``.stl`` files inside the allowed directories are
accepted. The allowed directories are the current working directory, or the
``PREWARP_ALLOWED_DIRS`` environment variable (``os.pathsep``-separated). The CLI does not use
this: there the user types the path.

Order matters, because resolving a path can already do harm (opening ``NUL``, or contacting
the host behind a UNC path or a mapped network drive):

1. the raw string is checked syntactically, without touching the filesystem;
2. it is made absolute lexically and must already lie inside an allowed directory, compared
   component by component (case-insensitively on Windows), so nothing outside is resolved;
3. it is walked one component at a time, and a symlink or junction is followed only after
   its target, read with ``readlink``, has passed steps 1 and 2.

What remains needs local write access to an allowed directory: swapping a checked component
for a link between the check and the load (a race), or the allowed directories themselves,
which come from the user's configuration and are trusted.
"""

from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath

IS_WINDOWS = os.name == "nt"

# Reserved DOS device names: reserved with any extension (NUL.stl) and trailing spaces.
_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{d}{n}" for d in ("COM", "LPT") for n in [*"0123456789", "¹", "²", "³"]
}


def allowed_dirs() -> list[Path]:
    """The allowed directories as written (made absolute) and as resolved, without duplicates.

    They come from the user's own configuration, so resolving them is trusted.
    """
    raw = os.environ.get("PREWARP_ALLOWED_DIRS")
    dirs = [d for d in raw.split(os.pathsep) if d.strip()] if raw else [os.getcwd()]
    out: list[Path] = []
    for d in dirs:
        for form in (Path(os.path.abspath(d)), Path(os.path.realpath(d))):
            if not any(_key(form) == _key(o) for o in out):
                out.append(form)
    return out


def _key(p: Path) -> tuple[str, ...]:
    """Path components, case-folded where the file system is case-insensitive."""
    return tuple(os.path.normcase(part) for part in p.parts)


def is_within(path: Path, root: Path) -> bool:
    """Component-wise containment: C:\\parts contains C:\\parts\\x but not C:\\parts-other\\x."""
    k, r = _key(path), _key(root)
    return len(k) >= len(r) and k[: len(r)] == r


def _syntax_error(raw: str) -> str | None:
    """Reasons to reject the string itself, decided without any filesystem access."""
    if not raw or "\x00" in raw:
        return "empty path or NUL byte"
    s = raw.replace("/", "\\")
    if s.startswith("\\\\"):  # \\server\share, //server/share, \\?\..., \\.\...
        return "UNC, device (\\\\.\\) and extended-length (\\\\?\\) paths are not allowed"
    if "://" in raw:
        return "URLs are not allowed"
    w = PureWindowsPath(s)
    if w.drive and not w.root:
        return "drive-relative paths (C:part.stl) are not allowed"
    if IS_WINDOWS and w.root and not w.drive:
        return "root-relative paths (\\part.stl) are not allowed; give the drive"
    for part in w.parts[1:] if w.anchor else w.parts:
        if ":" in part:
            return "':' inside a file name (alternate data stream) is not allowed"
        if part.split(".")[0].rstrip(" ").upper() in _DEVICES:
            return f"'{part}' is a reserved device name"
    return None


MAX_LINK_HOPS = 16


def _outside(path: str, shown: Path, roots: list[Path]) -> ValueError:
    return ValueError(
        f"{path}: {shown} is outside the allowed directories "
        f"({', '.join(map(str, roots))}); set PREWARP_ALLOWED_DIRS to widen them"
    )


def _link_target(link: Path) -> str:
    """Where a symlink or junction points, read without following it."""
    target = os.readlink(link)
    if target.startswith("\\\\?\\") and not target[4:].upper().startswith("UNC\\"):
        target = target[4:]  # junctions report \\?\C:\x; keep \\?\UNC\ so it is refused
    return target if os.path.isabs(target) else os.path.join(os.path.dirname(link), target)


def _walk(path: str, lexical: Path, roots: list[Path], hops: int = 0) -> Path:
    """Resolve ``lexical`` one component at a time, starting from an allowed root.

    Every symlink or junction on the way is read with ``readlink``, which does not follow
    it. Its target must pass the syntax and containment checks before anything under it is
    touched, so no path outside the allowed directories, and no network path, is ever opened
    or resolved, even through a link.
    """
    root = next((r for r in roots if is_within(lexical, r)), None)
    if root is None:
        raise _outside(path, lexical, roots)
    cur = root
    rest = lexical.parts[len(root.parts):]
    for n, part in enumerate(rest):
        nxt = cur / part
        if os.path.islink(nxt) or os.path.isjunction(nxt):
            if hops >= MAX_LINK_HOPS:
                raise ValueError(f"{path}: too many levels of links")
            target = _link_target(nxt)
            if reason := _syntax_error(target):
                raise ValueError(f"{path}: {nxt} links to {target}: {reason}")
            joined = Path(os.path.abspath(os.path.join(target, *rest[n + 1:])))
            return _walk(path, joined, roots, hops + 1)
        if not os.path.lexists(nxt):
            raise ValueError(f"{path}: file not found")
        cur = nxt
    return cur


def checked_stl_path(path: str) -> str:
    """Return the real path of an STL the LLM may open, or raise ValueError saying why not.

    1. The raw string is checked without touching the filesystem (``_syntax_error``).
    2. It is made absolute lexically (``abspath`` does no filesystem access) and must already
       lie inside an allowed directory: nothing outside one is ever resolved.
    3. It is walked component by component, and links are followed only after their target
       has passed steps 1 and 2 (``_walk``).
    """
    path = str(path)
    if reason := _syntax_error(path):
        raise ValueError(f"{path}: {reason}")
    if Path(path).suffix.lower() != ".stl":
        raise ValueError(f"{path}: only .stl files are accepted")
    lexical = Path(os.path.abspath(os.path.expanduser(path)))
    if reason := _syntax_error(str(lexical)):
        raise ValueError(f"{path}: {lexical}: {reason}")
    roots = allowed_dirs()
    final = _walk(path, lexical, roots)
    if final.suffix.lower() != ".stl":
        raise ValueError(f"{path}: resolves to {final}, which is not an .stl file")
    if not final.is_file():
        raise ValueError(f"{path}: not a regular file")
    real = Path(os.path.realpath(final))  # safe now: every link on the way was checked
    if not any(is_within(real, r) for r in roots):  # defence in depth
        raise _outside(path, real, roots)
    return str(real)
