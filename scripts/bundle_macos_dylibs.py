#!/usr/bin/env python3
"""Copy non-system Mach-O dependencies beside packaged ffmpeg tools."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from collections import deque
from pathlib import Path


SYSTEM_PREFIXES = ("/System/", "/usr/lib/")


def command(*args: str) -> str:
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout


def dependencies(path: Path) -> list[str]:
    lines = command("otool", "-L", str(path)).splitlines()[1:]
    return [line.strip().split(" (compatibility", 1)[0] for line in lines if line.strip()]


def dylib_id(path: Path) -> str | None:
    lines = command("otool", "-D", str(path)).splitlines()[1:]
    return lines[0].strip() if lines else None


def rpaths(path: Path) -> list[str]:
    lines = command("otool", "-l", str(path)).splitlines()
    values: list[str] = []
    for index, line in enumerate(lines):
        if line.strip() != "cmd LC_RPATH":
            continue
        for candidate in lines[index + 1 : index + 5]:
            value = candidate.strip()
            if value.startswith("path "):
                values.append(value.split(" ", 2)[1])
                break
    return values


def expand_token(value: str, owner: Path, executable_dir: Path) -> Path:
    return Path(
        value.replace("@loader_path", str(owner.parent)).replace(
            "@executable_path", str(executable_dir)
        )
    )


def resolve_dependency(value: str, owner: Path, executable_dir: Path) -> Path | None:
    if value.startswith(SYSTEM_PREFIXES):
        return None
    if value.startswith("@rpath/"):
        suffix = value.removeprefix("@rpath/")
        for entry in rpaths(owner):
            candidate = expand_token(entry, owner, executable_dir) / suffix
            if candidate.exists():
                return candidate.resolve()
        raise RuntimeError(f"Could not resolve {value} referenced by {owner}")
    candidate = expand_token(value, owner, executable_dir)
    if candidate.exists():
        return candidate.resolve()
    raise RuntimeError(f"Missing dependency {value} referenced by {owner}")


def unique_target(source: Path, lib_dir: Path, owners: dict[str, Path]) -> Path:
    target = lib_dir / source.name
    previous = owners.get(source.name)
    if previous is not None and previous != source:
        raise RuntimeError(f"Conflicting libraries named {source.name}: {previous} and {source}")
    owners[source.name] = source
    return target


def bundle(binaries: list[Path], lib_dir: Path) -> None:
    executable_dir = binaries[0].parent.resolve()
    if lib_dir.exists():
        shutil.rmtree(lib_dir)
    lib_dir.mkdir(parents=True)

    queue: deque[Path] = deque(path.resolve() for path in binaries)
    source_to_target = {path.resolve(): path.resolve() for path in binaries}
    owners: dict[str, Path] = {}
    dependency_maps: dict[Path, list[tuple[str, Path]]] = {}

    while queue:
        source = queue.popleft()
        pairs: list[tuple[str, Path]] = []
        own_id = dylib_id(source)
        for value in dependencies(source):
            if value == own_id:
                continue
            resolved = resolve_dependency(value, source, executable_dir)
            if resolved is None:
                continue
            target = source_to_target.get(resolved)
            if target is None:
                target = unique_target(resolved, lib_dir, owners)
                shutil.copy2(resolved, target)
                target.chmod(0o755)
                source_to_target[resolved] = target
                queue.append(resolved)
            pairs.append((value, target))
        dependency_maps[source] = pairs

    binary_sources = {path.resolve() for path in binaries}
    for source, target in source_to_target.items():
        if source not in binary_sources:
            subprocess.run(
                ["install_name_tool", "-id", f"@loader_path/{target.name}", str(target)],
                check=True,
            )
        for original, dependency_target in dependency_maps[source]:
            relative = (
                f"@loader_path/lib/{dependency_target.name}"
                if source in binary_sources
                else f"@loader_path/{dependency_target.name}"
            )
            subprocess.run(
                ["install_name_tool", "-change", original, relative, str(target)],
                check=True,
            )
        subprocess.run(["codesign", "--force", "--sign", "-", str(target)], check=True)

    print(f"Bundled {len(source_to_target) - len(binaries)} dylibs into {lib_dir}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", action="append", required=True, type=Path)
    parser.add_argument("--lib-dir", required=True, type=Path)
    args = parser.parse_args()
    bundle(args.binary, args.lib_dir)


if __name__ == "__main__":
    main()
