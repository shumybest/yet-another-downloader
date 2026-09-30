#!/usr/bin/env python3
"""Generate release manifests, notices, and corresponding-source inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.parse
from collections import deque
from pathlib import Path
from typing import Any

try:
    from scripts.bundle_macos_dylibs import dependencies, dylib_id, resolve_dependency
except ModuleNotFoundError:
    from bundle_macos_dylibs import dependencies, dylib_id, resolve_dependency


LICENSE_BASENAMES = re.compile(r"^(copying|copyright|license|notice)(\..*)?$", re.I)
IGNORABLE_TEST_RESOURCES = {("libogg", "oggfile"), ("libvorbis", "oggfile")}


def run(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        args,
        cwd=cwd,
        env=env,
        check=True,
        text=True,
        capture_output=True,
    ).stdout


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def reset_output_preserving_source_cache(output: Path, preserve: bool) -> None:
    source_cache = output / "homebrew-sources"
    saved_cache = output.parent / f".{output.name}-homebrew-sources-cache"
    if preserve and source_cache.exists():
        if saved_cache.exists():
            shutil.rmtree(saved_cache)
        source_cache.rename(saved_cache)
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    if preserve and saved_cache.exists():
        saved_cache.rename(source_cache)
    elif saved_cache.exists():
        shutil.rmtree(saved_cache)


def cellar_coordinates(path: Path) -> tuple[str, str] | None:
    parts = path.parts
    try:
        index = parts.index("Cellar")
    except ValueError:
        return None
    if len(parts) <= index + 2:
        return None
    return parts[index + 1], parts[index + 2]


def cellar_prefix(path: Path) -> Path | None:
    parts = path.parts
    try:
        index = parts.index("Cellar")
    except ValueError:
        return None
    if len(parts) <= index + 2:
        return None
    return Path(*parts[: index + 3])


def release_asset_names(version: str, architecture: str) -> dict[str, str]:
    return {
        "app_zip": f"yet-another-downloader-{version}-macos-{architecture}.zip",
        "dmg": f"yet-another-downloader-{version}-macos-{architecture}.dmg",
        "sources": f"yet-another-downloader-{version}-corresponding-source.tar.gz",
        "checksums": "SHA256SUMS.txt",
    }


def validate_formula_records(records: list[dict[str, Any]], output: Path | None = None) -> None:
    for record in records:
        name = record.get("name", "unknown formula")
        for field in ("formula", "receipt", "sources"):
            if not record.get(field):
                raise RuntimeError(f"{name} is missing required {field} material")
        if output is None:
            continue
        root = output.resolve()
        paths = [record["formula"], record["receipt"], *record["sources"]]
        for relative in paths:
            candidate = output / relative
            if not candidate.is_file():
                raise RuntimeError(f"{name} material does not exist: {relative}")
            if not candidate.resolve().is_relative_to(root):
                raise RuntimeError(f"{name} material escapes release directory: {relative}")
            if candidate.stat().st_size == 0:
                raise RuntimeError(f"{name} material is empty: {relative}")


def describe_path(path: Path) -> str:
    resolved = path.resolve()
    coordinates = cellar_coordinates(resolved)
    prefix = cellar_prefix(resolved)
    if coordinates and prefix:
        return str(Path("homebrew") / coordinates[0] / coordinates[1] / resolved.relative_to(prefix))
    if str(resolved).startswith(("/System/", "/usr/lib/")):
        return str(resolved)
    return resolved.name


def discover_macho_dependencies(binaries: list[Path]) -> tuple[list[Path], list[dict[str, str]]]:
    executable_dir = binaries[0].resolve().parent
    queue: deque[Path] = deque(path.resolve() for path in binaries)
    seen: set[Path] = set()
    graph: list[dict[str, str]] = []

    while queue:
        owner = queue.popleft()
        if owner in seen:
            continue
        seen.add(owner)
        own_id = dylib_id(owner)
        for value in dependencies(owner):
            if value == own_id:
                continue
            resolved = resolve_dependency(value, owner, executable_dir)
            if resolved is None:
                graph.append({"owner": describe_path(owner), "reference": value, "kind": "system"})
                continue
            resolved = resolved.resolve()
            graph.append(
                {
                    "owner": describe_path(owner),
                    "reference": value,
                    "resolved": describe_path(resolved),
                    "kind": "bundled",
                }
            )
            queue.append(resolved)
    return sorted(seen), sorted(graph, key=lambda item: (item["owner"], item["reference"]))


def copy_license_candidates(source: Path, destination: Path) -> list[str]:
    copied: list[str] = []
    for candidate in sorted(source.rglob("*")):
        if not candidate.is_file() or candidate.is_symlink():
            continue
        if not LICENSE_BASENAMES.match(candidate.name) or candidate.stat().st_size > 2 * 1024 * 1024:
            continue
        relative = candidate.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, target)
        copied.append(str(relative))
    return copied


def sanitize(value: Any) -> Any:
    home = str(Path.home())
    if isinstance(value, str):
        return value.replace(home, "$HOME")
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, dict):
        return {key: sanitize(item) for key, item in value.items()}
    return value


def formula_license(formula: Path) -> str:
    match = re.search(r'^\s*license\s+["\']([^"\']+)', formula.read_text(errors="replace"), re.M)
    return match.group(1) if match else "SEE-FORMULA"


def formula_primary_sha256(formula_text: str) -> str | None:
    match = re.search(r'^\s*sha256\s+["\']([0-9a-fA-F]{64})["\']', formula_text, re.M)
    return match.group(1).lower() if match else None


def primary_source_matches_formula(formula_text: str, source: Path) -> bool:
    if source.is_dir():
        return True
    expected_sha256 = formula_primary_sha256(formula_text)
    return expected_sha256 is None or sha256_file(source) == expected_sha256


def download_formula_primary_source(
    name: str, version: str, formula_text: str, source_root: Path
) -> Path:
    if re.search(r'^\s*(resource|patch)\b', formula_text, re.M):
        raise RuntimeError(f"Cannot use primary-source fallback for complex formula {name} {version}")
    url_match = re.search(r'^\s*url\s+["\']([^"\']+)', formula_text, re.M)
    expected_sha256 = formula_primary_sha256(formula_text)
    if not url_match or not expected_sha256:
        raise RuntimeError(f"Formula {name} {version} lacks a verifiable primary source")
    url = url_match.group(1)
    filename = Path(urllib.parse.urlparse(url).path).name or f"{name}-{version}.source"
    destination = source_root / "downloads" / f"manual--{name}-{version}--{filename}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "curl",
            "--location",
            "--fail-with-body",
            "--retry",
            "5",
            "--retry-all-errors",
            "--connect-timeout",
            "20",
            "--output",
            str(destination),
            url,
        ],
        check=True,
    )
    if sha256_file(destination) != expected_sha256:
        destination.unlink(missing_ok=True)
        raise RuntimeError(f"Primary source checksum mismatch for {name} {version}")
    return destination


def is_ignorable_homebrew_fetch_failure(name: str, formula_text: str, log: str) -> bool:
    match = re.search(
        rf"Resource\s+{re.escape(name)}--([^\s]+).*?Resource reports different checksum",
        log,
        re.S,
    )
    if not match:
        return False
    resource = match.group(1)
    if (name, resource) not in IGNORABLE_TEST_RESOURCES:
        return False
    resource_use = f'resource("{resource}")'
    install_block = formula_text.find("def install")
    test_block = formula_text.find("test do")
    if install_block >= 0 and test_block > install_block:
        if resource_use in formula_text[install_block:test_block]:
            return False
    return test_block >= 0 and formula_text.find(resource_use, test_block) >= test_block


def recover_failed_formula_resources(
    name: str,
    version: str,
    formula_text: str,
    log: str,
    prefix: Path,
    source_root: Path,
) -> list[Path]:
    failed = re.findall(
        rf'^Error: Failed to download resource "{re.escape(name)}--([^"\r\n]+)"$',
        log,
        re.M,
    )
    errors = re.findall(r'^Error:\s+(.+)$', log, re.M)
    if not failed or len(errors) != len(failed):
        return []

    blocks = {
        match.group("name"): match.group("body")
        for match in re.finditer(
            r'^[ \t]*resource[ \t]*(?:\([ \t]*)?["\'](?P<name>[^"\']+)["\']'
            r'[ \t]*\)?[ \t]+do[ \t]*$'
            r'(?P<body>.*?)^[ \t]*end[ \t]*$',
            formula_text,
            re.M | re.S,
        )
    }
    planned: list[tuple[Path, Path]] = []
    for resource_name in failed:
        block = blocks.get(resource_name)
        if block is None:
            return []
        url_match = re.search(r'^\s*url\s+["\']([^"\']+)', block, re.M)
        sha_match = re.search(r'^\s*sha256\s+["\']([0-9a-fA-F]{64})["\']', block, re.M)
        if not url_match or not sha_match:
            return []
        filename = Path(urllib.parse.unquote(urllib.parse.urlparse(url_match.group(1)).path)).name
        expected_sha256 = sha_match.group(1).lower()
        matches = [
            candidate
            for candidate in sorted(prefix.rglob(filename))
            if candidate.is_file() and sha256_file(candidate) == expected_sha256
        ]
        if not matches:
            return []
        safe_resource = re.sub(r"[^A-Za-z0-9._-]+", "-", resource_name)
        destination = (
            source_root
            / "downloads"
            / f"installed--{name}-{version}--{safe_resource}--{filename}"
        )
        planned.append((matches[0], destination))

    recovered: list[Path] = []
    for source, destination in planned:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        recovered.append(destination)
    return recovered


def archive_homebrew_vcs_sources(
    source_root: Path, output: Path, records: list[dict[str, Any]]
) -> list[dict[str, str]]:
    api_cache = source_root / "api"
    if api_cache.exists():
        shutil.rmtree(api_cache)

    vcs_records: list[dict[str, str]] = []
    checkouts = sorted(
        path for path in source_root.iterdir() if path.is_dir() and (path / ".git").is_dir()
    )
    for checkout in checkouts:
        commit = run("git", "-C", str(checkout), "rev-parse", "HEAD").strip()
        archive = checkout.with_suffix(".tar.gz")
        with tarfile.open(archive, "w:gz") as handle:
            for child in sorted(checkout.iterdir()):
                if child.name != ".git":
                    handle.add(child, arcname=f"{checkout.name}/{child.name}")
        vcs_records.append(
            {
                "cache_directory": checkout.name,
                "commit": commit,
                "archive": str(archive.relative_to(output)),
                "sha256": sha256_file(archive),
            }
        )
        checkout_path = str(checkout.relative_to(output))
        archive_path = str(archive.relative_to(output))
        for record in records:
            record["sources"] = [
                archive_path if item == checkout_path else item for item in record["sources"]
            ]
        shutil.rmtree(checkout)
    return vcs_records


def collect_homebrew_materials(
    files: list[Path], output: Path, fetch_sources: bool
) -> list[dict[str, Any]]:
    prefixes: dict[tuple[str, str], Path] = {}
    for path in files:
        coordinates = cellar_coordinates(path)
        prefix = cellar_prefix(path)
        if coordinates and prefix:
            prefixes[coordinates] = prefix

    records: list[dict[str, Any]] = []
    source_root = output / "homebrew-sources"
    if fetch_sources:
        source_root.mkdir(parents=True, exist_ok=True)
    for (name, version), prefix in sorted(prefixes.items()):
        safe_name = name.replace("@", "-")
        component_dir = output / "homebrew" / f"{safe_name}-{version}"
        formula_dir = component_dir / "formula"
        receipt_dir = component_dir / "receipt"
        license_dir = component_dir / "licenses"
        formula_dir.mkdir(parents=True, exist_ok=True)
        receipt_dir.mkdir(parents=True, exist_ok=True)

        formula_candidates = sorted((prefix / ".brew").glob("*.rb"))
        receipt = prefix / "INSTALL_RECEIPT.json"
        if len(formula_candidates) != 1 or not receipt.is_file():
            raise RuntimeError(f"Could not locate exact Homebrew metadata for {name} {version}")
        formula = formula_candidates[0]
        formula_target = formula_dir / formula.name
        shutil.copy2(formula, formula_target)
        receipt_target = receipt_dir / "INSTALL_RECEIPT.json"
        receipt_target.write_text(
            json.dumps(sanitize(json.loads(receipt.read_text())), ensure_ascii=False, indent=2) + "\n"
        )
        copied_licenses = copy_license_candidates(prefix, license_dir)

        source_files: list[str] = []
        fetch_warning: str | None = None
        recovered_resources: list[Path] = []
        if fetch_sources:
            env = os.environ.copy()
            env["HOMEBREW_CACHE"] = str(source_root)
            result = subprocess.run(
                ["brew", "fetch", "--formula", "--build-from-source", "--retry", str(formula)],
                env=env,
                text=True,
                capture_output=True,
            )
            fetch_log = result.stdout + result.stderr
            (component_dir / "fetch.log").write_text(fetch_log)
            try:
                cached = Path(
                    run(
                        "brew",
                        "--cache",
                        "--build-from-source",
                        str(formula),
                        env=env,
                    ).strip()
                ).resolve()
            except subprocess.CalledProcessError:
                if "Homebrew-installed `curl` is not installed" not in fetch_log:
                    raise
                cached = download_formula_primary_source(
                    name, version, formula.read_text(errors="replace"), source_root
                ).resolve()
                fetch_log += "\nPrimary source downloaded with system curl and SHA-256 verified.\n"
                (component_dir / "fetch.log").write_text(fetch_log)
            if not cached.exists() or not cached.is_relative_to(source_root.resolve()):
                raise RuntimeError(f"Could not locate fetched source for {name} {version}")
            formula_text = formula.read_text(errors="replace")
            if not primary_source_matches_formula(formula_text, cached):
                raise RuntimeError(f"Primary source checksum mismatch for {name} {version}")
            if result.returncode:
                fallback_used = "Primary source downloaded with system curl" in fetch_log
                recovered_resources = recover_failed_formula_resources(
                    name, version, formula_text, fetch_log, prefix, source_root
                )
                if (
                    not fallback_used
                    and not recovered_resources
                    and not is_ignorable_homebrew_fetch_failure(name, formula_text, fetch_log)
                ):
                    raise RuntimeError(f"Homebrew source fetch failed for {name} {version}")
                if fallback_used:
                    fetch_warning = (
                        "The historical formula required Homebrew curl, which is unavailable; the "
                        "single primary source was downloaded with system curl and passed its "
                        "formula SHA-256. See fetch.log."
                    )
                elif recovered_resources:
                    names = ", ".join(path.name for path in recovered_resources)
                    fetch_warning = (
                        "Historical formula resource URLs were unavailable; exact installed "
                        f"resources ({names}) were copied after matching their formula SHA-256. "
                        "See fetch.log."
                    )
                else:
                    fetch_warning = (
                        "Homebrew rejected a known non-build test resource whose upstream content "
                        "changed; the exact primary source passed its formula checksum. See fetch.log."
                    )
                for candidate in source_root.iterdir():
                    if candidate.is_symlink() and not candidate.exists():
                        candidate.unlink()
            source_files = [
                str(path.relative_to(output)) for path in [cached, *recovered_resources]
            ]

        records.append(
            {
                "name": name,
                "version": version,
                "license": formula_license(formula),
                "formula": str(formula_target.relative_to(output)),
                "receipt": str(receipt_target.relative_to(output)),
                "licenses": [str((license_dir / item).relative_to(output)) for item in copied_licenses],
                "sources": source_files,
                "fetch_warning": fetch_warning,
            }
        )
    if fetch_sources:
        vcs_records = archive_homebrew_vcs_sources(source_root, output, records)
        write_json(output / "HOMEBREW-VCS-SOURCES.json", vcs_records)
        validate_formula_records(records, output)
    return records


def collect_node_inventory(root: Path, output: Path) -> list[dict[str, Any]]:
    payload = json.loads(run("pnpm", "licenses", "list", "--prod", "--json", cwd=root))
    records: list[dict[str, Any]] = []
    license_root = output / "node-licenses"
    for expression, packages in sorted(payload.items()):
        for package in packages:
            record = {key: value for key, value in package.items() if key != "paths"}
            record["license"] = expression
            copied: list[str] = []
            for raw_path in package.get("paths", []):
                package_path = Path(raw_path)
                target = license_root / f"{package['name']}-{package['versions'][0]}"
                copied.extend(copy_license_candidates(package_path, target))
            record["license_files"] = sorted(set(copied))
            records.append(record)
    return records


def collect_cargo_inventory(root: Path, output: Path) -> list[dict[str, Any]]:
    payload = json.loads(
        run(
            "cargo",
            "metadata",
            "--offline",
            "--locked",
            "--manifest-path",
            str(root / "src-tauri/Cargo.toml"),
            "--format-version",
            "1",
        )
    )
    records: list[dict[str, Any]] = []
    license_root = output / "cargo-licenses"
    for package in sorted(payload["packages"], key=lambda item: (item["name"], item["version"])):
        package_root = Path(package["manifest_path"]).parent
        target = license_root / f"{package['name']}-{package['version']}"
        records.append(
            {
                "name": package["name"],
                "version": package["version"],
                "license": package.get("license"),
                "repository": package.get("repository"),
                "license_files": copy_license_candidates(package_root, target),
            }
        )
    return records


def collect_python_inventory(python: Path, output: Path) -> list[dict[str, Any]]:
    program = r'''
import json, sys
from importlib import metadata
from pathlib import Path
items=[]
for dist in metadata.distributions():
    name=dist.metadata.get('Name') or 'unknown'
    files=[]
    for item in dist.files or []:
        if item.name.lower().startswith(('license','copying','copyright','notice')):
            path=Path(dist.locate_file(item))
            if path.is_file(): files.append(str(path))
    items.append({'name':name,'version':dist.version,'license':dist.metadata.get('License-Expression') or dist.metadata.get('License'),'homepage':dist.metadata.get('Home-page'),'license_paths':files})
runtime=[]
runtime_roots=(
    Path(sys.prefix),
    Path(sys.prefix)/f'lib/python{sys.version_info.major}.{sys.version_info.minor}',
)
for root in runtime_roots:
    for name in ('LICENSE.txt','LICENSE'):
        path=root/name
        if path.is_file() and str(path) not in runtime: runtime.append(str(path))
print(json.dumps({'packages':items,'runtime_license_paths':runtime}))
'''
    payload = json.loads(run(str(python), "-I", "-c", program))
    license_root = output / "python-licenses"
    records: list[dict[str, Any]] = []
    for package in sorted(payload["packages"], key=lambda item: (item["name"].lower(), item["version"])):
        target = license_root / f"{package['name']}-{package['version']}"
        copied: list[str] = []
        for raw_path in package.pop("license_paths"):
            source = Path(raw_path)
            target.mkdir(parents=True, exist_ok=True)
            destination = target / source.name
            shutil.copy2(source, destination)
            copied.append(str(destination.relative_to(output)))
        package["license_files"] = copied
        records.append(package)
    runtime_target = license_root / "python-runtime"
    for raw_path in payload["runtime_license_paths"]:
        source = Path(raw_path)
        runtime_target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, runtime_target / source.name)
    return records


def collect_python_build_sources(
    python: Path, output: Path, records: list[dict[str, Any]]
) -> list[dict[str, str]]:
    build_packages = {"pyinstaller", "pyinstaller-hooks-contrib"}
    source_root = output / "python-sources"
    source_root.mkdir(parents=True, exist_ok=True)
    sources: list[dict[str, str]] = []
    for package in records:
        name = str(package["name"])
        version = str(package["version"])
        if name.lower() not in build_packages:
            continue
        before = set(source_root.iterdir())
        run(
            str(python),
            "-I",
            "-m",
            "pip",
            "download",
            "--disable-pip-version-check",
            "--no-deps",
            "--no-binary=:all:",
            "--dest",
            str(source_root),
            f"{name}=={version}",
        )
        created = sorted(path for path in source_root.iterdir() if path not in before)
        if len(created) != 1:
            raise RuntimeError(f"Could not identify source distribution for {name} {version}")
        archive = created[0]
        sources.append(
            {
                "name": name,
                "version": version,
                "archive": str(archive.relative_to(output)),
                "sha256": sha256_file(archive),
            }
        )
    missing = build_packages - {item["name"].lower() for item in sources}
    if missing:
        raise RuntimeError(f"Missing Python build-tool source distributions: {sorted(missing)}")
    return sources


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def generate(args: argparse.Namespace) -> None:
    root = args.project_root.resolve()
    output = args.output.resolve()
    reset_output_preserving_source_cache(output, args.fetch_sources)

    binaries = [args.ffmpeg.resolve(), args.ffprobe.resolve()]
    files, graph = discover_macho_dependencies(binaries)
    homebrew = collect_homebrew_materials(files, output, args.fetch_sources)
    node = collect_node_inventory(root, output)
    cargo = collect_cargo_inventory(root, output)
    python = collect_python_inventory(args.python.resolve(), output)
    python_sources = (
        collect_python_build_sources(args.python.resolve(), output, python)
        if args.fetch_sources
        else []
    )

    (output / "FFMPEG-BUILDCONF.txt").write_text(run(str(args.ffmpeg), "-buildconf"))
    (output / "FFMPEG-LICENSE.txt").write_text(run(str(args.ffmpeg), "-L"))
    write_json(output / "MACHO-DEPENDENCIES.json", graph)
    write_json(output / "HOMEBREW-COMPONENTS.json", homebrew)
    write_json(output / "NODE-DEPENDENCIES.json", node)
    write_json(output / "CARGO-DEPENDENCIES.json", cargo)
    write_json(output / "PYTHON-DEPENDENCIES.json", python)
    write_json(output / "PYTHON-BUILD-SOURCES.json", python_sources)
    write_json(
        output / "RELEASE-MANIFEST.json",
        {
            "version": args.version,
            "architecture": args.architecture,
            "ffmpeg_sha256": sha256_file(args.ffmpeg),
            "ffprobe_sha256": sha256_file(args.ffprobe),
            "homebrew_components": len(homebrew),
            "macho_files": len(files),
        },
    )
    (output / "SOURCE-OFFER.txt").write_text(
        "Corresponding source and build materials for this binary are provided with the "
        f"{args.version} release at https://github.com/shumybest/yet-another-downloader/releases/tag/{args.version}.\n"
    )
    print(f"Compliance materials written to {output} ({len(homebrew)} Homebrew components).")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ffmpeg", type=Path, required=True)
    parser.add_argument("--ffprobe", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--architecture", required=True)
    parser.add_argument("--fetch-sources", action="store_true")
    generate(parser.parse_args())


if __name__ == "__main__":
    main()
