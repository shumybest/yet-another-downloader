#!/usr/bin/env python3
"""Reject files and content that should not enter the public repository."""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


MAX_SOURCE_BYTES = 10 * 1024 * 1024
GENERATED_PARTS = {'build', 'dist', 'target', 'binaries', 'resources', '__pycache__'}
GENERATED_SUFFIXES = {'.app', '.db', '.dmg', '.dylib', '.exe', '.log', '.p12', '.pyc', '.sqlite', '.sqlite3', '.zip'}
SENSITIVE_SUFFIXES = {'.key', '.mobileprovision', '.p12', '.pem'}
SENSITIVE_NAMES = {'credentials.json', 'vod.json'}
CONTENT_PATTERNS = (
    ('private-key', re.compile(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----')),
    ('tencent-key', re.compile(r'AKID[A-Za-z0-9]{12,}')),
    ('github-token', re.compile(r'\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b')),
    ('embedded-password', re.compile(r'https?://[^\s/:]+:[^\s/@]+@')),
    ('bearer-token', re.compile(r'Authorization:\s*Bearer\s+(?!<token>|\$token)[A-Za-z0-9._~+/-]{16,}')),
    ('signed-query', re.compile(r'(?:pass_ticket|exportkey|encfilekey|signature|X-Amz-Signature)=[A-Za-z0-9_%+./-]{16,}', re.IGNORECASE)),
    ('personal-path', re.compile('/' + r'Users/(?!Shared(?:/|\b))[^/\s]+/')),
    ('private-author-domain', re.compile('@' + r'limaxs\.com\b', re.IGNORECASE)),
)


@dataclass(frozen=True)
class Finding:
    kind: str
    path: Path
    line: int | None = None

    def render(self) -> str:
        location = f'{self.path}:{self.line}' if self.line else str(self.path)
        return f'{self.kind}: {location}'


def _is_sensitive_filename(path: Path) -> bool:
    name = path.name.lower()
    if name == '.env.example':
        return False
    return name == '.env' or name.startswith('.env.') or name in SENSITIVE_NAMES or path.suffix.lower() in SENSITIVE_SUFFIXES


def _is_generated(path: Path) -> bool:
    parts = set(path.parts)
    if parts & GENERATED_PARTS:
        return True
    return path.suffix.lower() in GENERATED_SUFFIXES


def scan_paths(root: Path, paths: list[Path]) -> list[Finding]:
    findings: list[Finding] = []
    for relative in paths:
        path = root / relative
        if not path.is_file():
            continue
        if _is_sensitive_filename(relative):
            findings.append(Finding('sensitive-filename', relative))
            continue
        if _is_generated(relative):
            findings.append(Finding('generated-artifact', relative))
            continue
        if path.stat().st_size > MAX_SOURCE_BYTES:
            findings.append(Finding('oversized-file', relative))
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for kind, pattern in CONTENT_PATTERNS:
                if pattern.search(line):
                    findings.append(Finding(kind, relative, line_number))
    return findings


def candidate_paths(root: Path) -> list[Path]:
    result = subprocess.run(
        ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z'],
        cwd=root,
        check=True,
        capture_output=True,
    )
    return [Path(value.decode()) for value in result.stdout.split(b'\0') if value]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    findings = scan_paths(root, candidate_paths(root))
    if findings:
        print('Public-tree check failed:', file=sys.stderr)
        for finding in findings:
            print(f'  {finding.render()}', file=sys.stderr)
        return 1
    print('Public-tree check passed.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
