"""Path checks for file names that come from an LLM (MCP clients, the Claude agent).

A prompt-injected model could otherwise ask the solver to open any file on the machine, or a
UNC path (``\\\\host\\share\\x.stl``) that makes Windows authenticate to a remote host and hand
it the user's NTLM hash. Only existing local ``.stl`` files inside the allowed directories are
accepted. The allowed directories are the current working directory, or the
``PREWARP_ALLOWED_DIRS`` environment variable (``os.pathsep``-separated). The CLI does not use
this: there the user types the path.

Order matters: the raw string is checked syntactically first, without touching the
filesystem (resolving ``NUL`` or a UNC path would already open the device or contact the
host). Only then is the real path resolved, following symlinks and junctions, and compared
with the allowed directories component by component (case-insensitively on Windows).
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
    raw = os.environ.get("PREWARP_ALLOWED_DIRS")
    dirs = [d for d in raw.split(os.pathsep) if d.strip()] if raw else [os.getcwd()]
    return [Path(os.path.realpath(d)) for d in dirs]


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


def checked_stl_path(path: str) -> str:
    """Return the real path of an STL the LLM may open, or raise ValueError saying why not."""
    path = str(path)
    if reason := _syntax_error(path):
        raise ValueError(f"{path}: {reason}")
    if Path(path).suffix.lower() != ".stl":
        raise ValueError(f"{path}: only .stl files are accepted")
    real = Path(os.path.realpath(os.path.expanduser(path)))  # follows symlinks and junctions
    if reason := _syntax_error(str(real)):
        raise ValueError(f"{path}: resolves to {real}: {reason}")
    if real.suffix.lower() != ".stl":
        raise ValueError(f"{path}: resolves to {real}, which is not an .stl file")
    roots = allowed_dirs()
    if not any(is_within(real, r) for r in roots):
        raise ValueError(
            f"{path}: resolves to {real}, outside the allowed directories "
            f"({', '.join(map(str, roots))}); set PREWARP_ALLOWED_DIRS to widen them"
        )
    if not real.is_file():
        raise ValueError(f"{path}: file not found")
    return str(real)
