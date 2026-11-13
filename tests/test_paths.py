"""LLM-supplied paths and resource limits (prompt-injection / memory-exhaustion guards)."""

import os
import sys
from pathlib import Path

import numpy as np
import pytest
import trimesh

from prewarp import limits, service
from prewarp.paths import checked_stl_path, is_within

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows path semantics")


@pytest.fixture
def parts(tmp_path, monkeypatch):
    root = tmp_path / "parts"
    root.mkdir()
    trimesh.creation.box(extents=(10, 10, 10)).export(root / "part.stl")
    (root / "secret.txt").write_text("x")
    monkeypatch.setenv("PREWARP_ALLOWED_DIRS", str(root))
    return root


def _link_dir(link: Path, target: Path) -> None:
    """Directory symlink, or a junction on Windows without symlink privilege."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        if sys.platform != "win32":
            raise
        import _winapi

        _winapi.CreateJunction(str(target), str(link))


def test_accepts_an_stl_inside_the_allowed_dir(parts):
    assert checked_stl_path(str(parts / "part.stl")) == os.path.realpath(parts / "part.stl")


def test_rejects_other_files_and_outside_paths(parts):
    (parts.parent / "elsewhere.stl").write_text("solid x\nendsolid x\n")
    for bad in [parts / "secret.txt", parts.parent / "elsewhere.stl", parts / ".." / "elsewhere.stl",
                parts / "missing.stl", "https://example.com/x.stl", ""]:
        with pytest.raises(ValueError):
            checked_stl_path(str(bad))


def test_prefix_is_not_containment(parts):
    sibling = parts.parent / (parts.name + "-other")
    sibling.mkdir()
    trimesh.creation.box(extents=(1, 1, 1)).export(sibling / "x.stl")
    assert not is_within(sibling / "x.stl", parts)
    with pytest.raises(ValueError, match="outside the allowed"):
        checked_stl_path(str(sibling / "x.stl"))


def test_links_are_resolved_before_the_containment_check(parts):
    outside = parts.parent / "outside"
    outside.mkdir()
    trimesh.creation.box(extents=(1, 1, 1)).export(outside / "x.stl")
    _link_dir(parts / "link", outside)  # allowed/link -> outside
    with pytest.raises(ValueError, match="outside the allowed"):
        checked_stl_path(str(parts / "link" / "x.stl"))


def test_link_into_a_non_stl_file_is_rejected(parts):
    try:
        os.symlink(parts / "secret.txt", parts / "alias.stl")
    except OSError:
        pytest.skip("file symlinks need privileges here")
    with pytest.raises(ValueError, match="not an .stl"):
        checked_stl_path(str(parts / "alias.stl"))


@windows_only
def test_case_insensitive_on_windows(parts, monkeypatch):
    monkeypatch.setenv("PREWARP_ALLOWED_DIRS", str(parts).upper())
    assert checked_stl_path(str(parts / "PART.STL").lower())


@pytest.mark.parametrize("raw", [
    r"\\?\C:\parts\x.stl",          # extended-length prefix
    r"\\.\C:\parts\x.stl",          # device namespace
    r"\\evil-host\share\x.stl",     # UNC
    "//evil-host/share/x.stl",      # UNC with forward slashes
    "/\\evil-host/share/x.stl",     # mixed separators
    "C:pieza.stl",                  # drive-relative
    "pieza.stl:oculto",             # alternate data stream
    "secret.txt:payload.stl",       # ADS with an .stl-looking suffix
    "NUL.stl", "con.stl", "COM1.stl", "lpt9.stl", "AUX .stl", "COM¹.stl",
    "dir/NUL/x.stl",                # device name as a directory component
])
def test_rejected_before_touching_the_filesystem(raw, parts, monkeypatch):
    # Worst case: working directory = allowed directory (the default), so relative names
    # would land inside it. They must be refused on syntax alone, before any resolution.
    monkeypatch.chdir(parts)
    trimesh.creation.box(extents=(1, 1, 1)).export(parts / "pieza.stl")

    def no_fs(*_a, **_k):
        raise AssertionError("filesystem touched")

    monkeypatch.setattr(os.path, "realpath", no_fs)
    monkeypatch.setattr(Path, "is_file", no_fs)
    with pytest.raises(ValueError):
        checked_stl_path(raw)


@windows_only
def test_root_relative_rejected_on_windows(parts):
    with pytest.raises(ValueError, match="root-relative"):
        checked_stl_path(r"\parts\x.stl")


def test_stl_size_limit(parts, monkeypatch):
    monkeypatch.setenv("PREWARP_MAX_STL_MB", "0.000001")
    with pytest.raises(limits.ResourceLimitError, match="PREWARP_MAX_STL_MB"):
        service.analyze_part(str(parts / "part.stl"), render=False, output_dir=str(parts / "out"))


def test_grid_limit_is_checked_before_voxelising(parts, monkeypatch):
    monkeypatch.setenv("PREWARP_MAX_ELEMENTS", "1000")  # grid limit 20k cells
    calls = []
    monkeypatch.setattr(service, "mesh_from_stl", lambda *a: calls.append(a))
    with pytest.raises(limits.ResourceLimitError, match="PREWARP_MAX_GRID_CELLS"):
        service.analyze_part(str(parts / "part.stl"), pitch_mm=0.1, render=False)
    assert not calls  # failed before allocating the grid


def test_element_limit_before_simulating(parts, monkeypatch):
    monkeypatch.setenv("PREWARP_MAX_ELEMENTS", "100")
    monkeypatch.setenv("PREWARP_MAX_GRID_CELLS", "1e9")
    monkeypatch.setattr(service, "simulate_build", lambda *a, **k: pytest.fail("simulated"))
    with pytest.raises(limits.ResourceLimitError, match="1,000 elements, above the 100"):
        service.analyze_part(str(parts / "part.stl"), pitch_mm=1.0, render=False)


def test_limit_errors_are_not_mistaken_for_infeasible_orientations(parts, monkeypatch):
    monkeypatch.setenv("PREWARP_MAX_ELEMENTS", "10")
    with pytest.raises(limits.ResourceLimitError):
        service.rank_orientations(str(parts / "part.stl"), orientations=[[0, 0]])


@pytest.mark.parametrize("value", ["abc", "0", "-5"])
def test_bad_limit_values_fail_clearly(value, monkeypatch):
    monkeypatch.setenv("PREWARP_MAX_ELEMENTS", value)
    with pytest.raises(ValueError, match="PREWARP_MAX_ELEMENTS"):
        limits.max_elements()


def test_defaults_allow_the_validated_nist_runs():
    # 0.5 mm bridges (~29.5k elements) must pass with default limits.
    limits.check_elements(29_500, 0.5)
    limits.check_grid(np.array([[0, 0, 0], [75, 10, 12.5]]), 0.5)
