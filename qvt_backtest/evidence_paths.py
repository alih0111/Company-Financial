"""Rebase archived evidence paths without changing immutable evidence bytes."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath


def provenance_path(value: str | Path, root: str | Path) -> str:
    """Keep in-project paths relative and retain the real path for external inputs."""
    path = Path(value).resolve()
    try:
        return path.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_evidence_path(value: str | Path) -> Path:
    old = os.environ.get("CDF_EVIDENCE_OLD_ROOT")
    new = os.environ.get("CDF_EVIDENCE_NEW_ROOT")
    if not old and not new:
        return Path(value)
    if not old or not new:
        raise ValueError("EVIDENCE_REBASE_REQUIRES_BOTH_ROOTS")
    new_root = Path(new).resolve()
    raw = str(value)
    current = Path(raw)
    if current.is_absolute() and current.resolve().is_relative_to(new_root):
        return current
    if "\\" in old or PureWindowsPath(old).drive:
        try:
            relative = PureWindowsPath(raw).relative_to(PureWindowsPath(old))
        except ValueError:
            raise ValueError("EVIDENCE_PATH_OUTSIDE_ORIGINAL_ROOT") from None
        parts = relative.parts
    else:
        try:
            parts = Path(raw).relative_to(Path(old)).parts
        except ValueError:
            raise ValueError("EVIDENCE_PATH_OUTSIDE_ORIGINAL_ROOT") from None
    if ".." in parts:
        raise ValueError("EVIDENCE_PATH_TRAVERSAL")
    mapped = new_root.joinpath(*parts)
    if not mapped.resolve().is_relative_to(new_root):
        raise ValueError("EVIDENCE_PATH_OUTSIDE_RESTORED_ROOT")
    return mapped
