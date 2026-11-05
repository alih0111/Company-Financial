"""Package selected, hash-pinned artifacts; this is not a complete recovery bundle."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

MANIFEST = "selected-artifact-inventory.json"


def safe_name(value: str) -> str:
    path = PurePosixPath(value)
    if (not value or "\\" in value or path.is_absolute() or ".." in path.parts
            or value == "EXTERNAL_PATH_REDACTED" or ":" in value):
        raise ValueError("UNSAFE_ARTIFACT_PATH")
    return path.as_posix()


def records(inventory: dict) -> list[dict]:
    entries = inventory.get("artifacts")
    if not isinstance(entries, list) or not entries:
        raise ValueError("ARTIFACT_INVENTORY_EMPTY")
    names = set()
    for item in entries:
        name = safe_name(item["path"])
        if name == MANIFEST or name in names or not item.get("present"):
            raise ValueError("ARTIFACT_INVENTORY_INVALID")
        if not isinstance(item.get("bytes"), int) or item["bytes"] < 0:
            raise ValueError("ARTIFACT_SIZE_INVALID")
        digest = item.get("sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError("ARTIFACT_HASH_INVALID")
        names.add(name)
    return entries


def copy_and_hash(source, target) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    while chunk := source.read(1024 * 1024):
        target.write(chunk)
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def make_package(root: Path, inventory_path: Path, output: Path) -> None:
    root, output = root.resolve(), output.resolve()
    inventory_bytes = inventory_path.read_bytes()
    inventory = json.loads(inventory_bytes)
    entries = records(inventory)
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise FileExistsError("PACKAGE_ALREADY_EXISTS")
    fd, temp_name = tempfile.mkstemp(prefix=".artifact-package-", suffix=".tmp", dir=output.parent)
    os.close(fd)
    temporary = Path(temp_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr(MANIFEST, inventory_bytes)
            for item in entries:
                name = safe_name(item["path"])
                source = (root / name).resolve()
                if not source.is_relative_to(root) or not source.is_file():
                    raise ValueError("ARTIFACT_SOURCE_MISSING_OR_OUTSIDE_ROOT")
                with source.open("rb") as src, archive.open(name, "w") as dst:
                    size, digest = copy_and_hash(src, dst)
                if (size, digest) != (item["bytes"], item["sha256"]):
                    raise ValueError("ARTIFACT_CHANGED_SINCE_INVENTORY")
        verify_package(temporary)
        # Create the final name exclusively; never replace an existing backup.
        os.link(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def verify_package(package: Path) -> list[dict]:
    with zipfile.ZipFile(package) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or names.count(MANIFEST) != 1:
            raise ValueError("PACKAGE_MEMBERS_INVALID")
        entries = records(json.loads(archive.read(MANIFEST)))
        if set(names) != {MANIFEST, *(safe_name(item["path"]) for item in entries)}:
            raise ValueError("PACKAGE_MEMBERS_INVALID")
        for item in entries:
            info = archive.getinfo(safe_name(item["path"]))
            if info.file_size != item["bytes"]:
                raise ValueError("PACKAGE_SIZE_MISMATCH")
            digest = hashlib.sha256()
            with archive.open(info) as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != item["sha256"]:
                raise ValueError("PACKAGE_HASH_MISMATCH")
        return entries


def restore_package(package: Path, destination: Path) -> None:
    entries = verify_package(package)
    destination = destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(package) as archive:
        for item in entries:
            name = safe_name(item["path"])
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(name) as source, target.open("xb") as output:
                size, digest = copy_and_hash(source, output)
            if (size, digest) != (item["bytes"], item["sha256"]):
                raise ValueError("RESTORED_ARTIFACT_MISMATCH")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    create = sub.add_parser("create")
    create.add_argument("--root", type=Path, required=True)
    create.add_argument("--inventory", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--package", type=Path, required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--package", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.action == "create":
        make_package(args.root, args.inventory, args.output)
    elif args.action == "verify":
        verify_package(args.package)
    else:
        restore_package(args.package, args.destination)
    print("OK: selected artifacts only; this is not a complete recovery bundle")


if __name__ == "__main__":
    main()
