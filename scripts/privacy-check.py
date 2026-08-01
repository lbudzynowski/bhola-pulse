#!/usr/bin/env python3
"""Fail-closed privacy checks for tracked repository content."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import struct
import subprocess
import sys
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence
from urllib.parse import urlsplit


MAX_FILE_SIZE = 5 * 1024 * 1024
MAX_APPROVED_PNG_SIZE = 2 * 1024 * 1024
DENYLIST_ENV = "BHOLA_PRIVACY_DENYLIST_FILE"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
APPROVED_PNG_DIMENSIONS = {
    "docs/images/large-sharp.png": (958, 721),
    "docs/images/nerd-mode.png": (958, 721),
}
ALLOWED_PNG_CHUNKS = frozenset({b"IHDR", b"IDAT", b"IEND"})

HOME_PATH_PATTERNS = (
    re.compile(r"/" r"home/[^/\s'\"`]+(?:/[^\s'\"`]*)?"),
    re.compile(r"/" r"Users/[^/\s'\"`]+(?:/[^\s'\"`]*)?"),
    re.compile(r"[A-Za-z]:\\" r"Users\\[^\\\s'\"`]+(?:\\[^\s'\"`]*)?", re.I),
)
PRIVATE_KEY_PATTERN = re.compile(
    r"-----BEGIN " r"(?:RSA |EC |DSA |OPENSSH )?" r"PRIVATE KEY-----"
)
AUTHORIZATION_PATTERN = re.compile(
    r"(?i)Authorization" r"\s*:\s*Bearer\s+[^\s'\"`]+"
)
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(?:api[_-]?key|apikey|aws_secret_access_key|client[_-]?secret|password|passwd|secret|token)\b"
    r"\s*(?::|=)\s*['\"]?([^'\"\s,;}]{6,})"
)
URL_PATTERN = re.compile(r"(?i)\b[a-z][a-z0-9+.-]*://[^\s<>\"']+")
TOKEN_PATTERNS = (
    re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{30,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    re.compile(r"\bglpat-[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\bnpm_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bsk_live_[A-Za-z0-9]{16,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\b[0-9]{7,12}:[A-Za-z0-9_-]{30,}\b"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)
SUSPICIOUS_SUFFIXES = {".env", ".pem", ".key", ".p12", ".pfx", ".kdbx"}


class DenylistConfigurationError(Exception):
    """Raised for unsafe or unreadable private denylist configuration."""


@dataclass(frozen=True)
class Finding:
    category: str
    path: str
    line: int
    fragment: str


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", "surrogateescape")).hexdigest()[:12]


def _redacted_fragment(category: str, value: str) -> str:
    return f"<redacted:{category}:{_fingerprint(value)}>"


def _sanitize_path(path: str) -> str:
    result = path
    for pattern in HOME_PATH_PATTERNS:
        result = pattern.sub("<redacted-home-path>", result)
    return result


def _finding(category: str, path: str, line: int, value: str) -> Finding:
    return Finding(
        category=category,
        path=_sanitize_path(path),
        line=line,
        fragment=_redacted_fragment(category, value),
    )


def load_denylist(
    environ: Mapping[str, str] | None = None,
    *,
    repository: Path | None = None,
) -> tuple[str, ...]:
    environment = os.environ if environ is None else environ
    configured_path = environment.get(DENYLIST_ENV)
    if not configured_path:
        return ()

    try:
        denylist_path = Path(configured_path).expanduser().resolve(strict=True)
        if repository is not None and denylist_path.is_relative_to(repository.resolve()):
            raise DenylistConfigurationError(
                "configured denylist must be stored outside the repository"
            )
        content = denylist_path.read_text(encoding="utf-8")
    except DenylistConfigurationError:
        raise
    except (OSError, UnicodeError) as error:
        raise DenylistConfigurationError(
            "configured denylist is unreadable"
        ) from error

    values: list[str] = []
    for line in content.splitlines():
        value = line.strip()
        if not value or value.startswith("#"):
            continue
        if len(value) < 4:
            raise DenylistConfigurationError(
                "configured denylist contains a value shorter than 4 characters"
            )
        values.append(value)
    return tuple(values)


def _scan_denylist(
    path: str,
    line: int,
    value: str,
    denylist: Sequence[str],
) -> list[Finding]:
    folded_value = value.casefold()
    return [
        _finding("private_denylist", path, line, forbidden)
        for forbidden in denylist
        if forbidden.casefold() in folded_value
    ]


def _scan_name(path: str, denylist: Sequence[str]) -> list[Finding]:
    findings = _scan_denylist(path, 0, path, denylist)
    name = Path(path).name.lower()
    suffix = Path(name).suffix.lower()

    for pattern in HOME_PATH_PATTERNS:
        for match in pattern.finditer(path):
            findings.append(_finding("absolute_home_path", path, 0, match.group(0)))
    if name == ".env" or name.startswith(".env.") or suffix in SUSPICIOUS_SUFFIXES:
        findings.append(_finding("suspicious_filename", path, 0, name))
    return findings


def _scan_line(
    path: str,
    number: int,
    line: str,
    denylist: Sequence[str],
) -> list[Finding]:
    findings = _scan_denylist(path, number, line, denylist)
    for pattern in HOME_PATH_PATTERNS:
        for match in pattern.finditer(line):
            findings.append(_finding("absolute_home_path", path, number, match.group(0)))
    for match in PRIVATE_KEY_PATTERN.finditer(line):
        findings.append(_finding("private_key", path, number, match.group(0)))
    for pattern in TOKEN_PATTERNS:
        for match in pattern.finditer(line):
            findings.append(_finding("credential_token", path, number, match.group(0)))
    for match in AUTHORIZATION_PATTERN.finditer(line):
        findings.append(_finding("authorization_bearer", path, number, match.group(0)))
    for match in SECRET_ASSIGNMENT_PATTERN.finditer(line):
        findings.append(_finding("secret_assignment", path, number, match.group(0)))
    for match in URL_PATTERN.finditer(line):
        url = match.group(0).rstrip(".,);]")
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.username is not None or parsed.password is not None:
            findings.append(_finding("url_embedded_credentials", path, number, url))
    return findings


def _png_finding(category: str, path: str) -> list[Finding]:
    return [_finding(category, path, 0, category)]


def _scan_approved_png(
    path: str,
    data: bytes,
    expected_dimensions: tuple[int, int],
) -> list[Finding]:
    if not data or len(data) > MAX_APPROVED_PNG_SIZE:
        return _png_finding("approved_png_invalid_size", path)
    if not data.startswith(PNG_SIGNATURE):
        return _png_finding("approved_png_invalid_signature", path)

    offset = len(PNG_SIGNATURE)
    chunk_index = 0
    ihdr_count = 0
    idat_count = 0
    iend_count = 0

    while offset < len(data):
        if len(data) - offset < 12:
            return _png_finding("approved_png_truncated_chunk", path)

        chunk_length = struct.unpack(">I", data[offset : offset + 4])[0]
        chunk_type = data[offset + 4 : offset + 8]
        chunk_end = offset + 12 + chunk_length
        if chunk_end > len(data):
            return _png_finding("approved_png_truncated_chunk", path)

        chunk_data = data[offset + 8 : offset + 8 + chunk_length]
        stored_crc = struct.unpack(">I", data[chunk_end - 4 : chunk_end])[0]
        calculated_crc = zlib.crc32(chunk_type)
        calculated_crc = zlib.crc32(chunk_data, calculated_crc) & 0xFFFFFFFF
        if stored_crc != calculated_crc:
            return _png_finding("approved_png_invalid_crc", path)
        if chunk_type not in ALLOWED_PNG_CHUNKS:
            return _png_finding("approved_png_unexpected_chunk", path)
        if chunk_index == 0 and chunk_type != b"IHDR":
            return _png_finding("approved_png_ihdr_not_first", path)

        if chunk_type == b"IHDR":
            ihdr_count += 1
            if ihdr_count != 1:
                return _png_finding("approved_png_duplicate_ihdr", path)
            if chunk_length != 13:
                return _png_finding("approved_png_invalid_ihdr", path)
            dimensions = struct.unpack(">II", chunk_data[:8])
            if dimensions != expected_dimensions:
                return _png_finding("approved_png_unexpected_dimensions", path)
        elif chunk_type == b"IDAT":
            idat_count += 1
        else:
            iend_count += 1
            if chunk_length != 0 or iend_count != 1:
                return _png_finding("approved_png_invalid_iend", path)
            if chunk_end != len(data):
                return _png_finding("approved_png_trailing_data", path)

        offset = chunk_end
        chunk_index += 1

    if ihdr_count != 1:
        return _png_finding("approved_png_missing_ihdr", path)
    if idat_count == 0:
        return _png_finding("approved_png_missing_idat", path)
    if iend_count != 1:
        return _png_finding("approved_png_missing_iend", path)
    return []


def scan_bytes(
    path: str,
    data: bytes,
    *,
    denylist: Sequence[str] = (),
) -> list[Finding]:
    findings = _scan_name(path, denylist)
    expected_dimensions = APPROVED_PNG_DIMENSIONS.get(path)
    if expected_dimensions is not None:
        findings.extend(_scan_approved_png(path, data, expected_dimensions))
        return findings
    if len(data) > MAX_FILE_SIZE:
        findings.append(_finding("large_file_unscanned", path, 0, str(len(data))))
        return findings
    if b"\x00" in data[:8192]:
        findings.append(_finding("binary_file_unscanned", path, 0, str(len(data))))
        return findings
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        findings.append(_finding("binary_file_unscanned", path, 0, str(len(data))))
        return findings
    for number, line in enumerate(text.splitlines(), 1):
        findings.extend(_scan_line(path, number, line, denylist))
    return findings


def _read_path(path: Path) -> bytes:
    if path.is_symlink():
        return os.readlink(path).encode("utf-8", "surrogateescape")
    return path.read_bytes()


def tracked_paths(repository: Path) -> list[Path]:
    output = subprocess.check_output(
        ["git", "-C", str(repository), "ls-files", "-z"]
    )
    return [
        repository / item.decode("utf-8", "surrogateescape")
        for item in output.split(b"\x00")
        if item
    ]


def scan_paths(
    paths: Iterable[Path],
    *,
    display_root: Path | None = None,
    denylist: Sequence[str] = (),
) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        try:
            display_path = str(path.relative_to(display_root)) if display_root else str(path)
        except ValueError:
            display_path = str(path)
        try:
            data = _read_path(path)
        except OSError as error:
            findings.append(
                _finding(
                    "unreadable_tracked_file",
                    display_path,
                    0,
                    error.__class__.__name__,
                )
            )
            continue
        findings.extend(scan_bytes(display_path, data, denylist=denylist))
    return findings


def format_finding(finding: Finding) -> str:
    if finding.category == "private_denylist":
        return f"{finding.category}: {finding.fragment}"
    return (
        f"{finding.category}: {finding.path}:{finding.line}: "
        f"{finding.fragment}"
    )


def repository_root() -> Path:
    output = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"], text=True
    ).strip()
    return Path(output)


def run(paths: Sequence[str]) -> int:
    root = repository_root()
    try:
        denylist = load_denylist(repository=root)
    except DenylistConfigurationError as error:
        print(f"privacy_denylist_error: {error}", file=sys.stderr)
        return 2

    if paths:
        selected = [Path(item) for item in paths]
        findings = scan_paths(selected, denylist=denylist)
        scanned_count = len(selected)
    else:
        selected = tracked_paths(root)
        findings = scan_paths(selected, display_root=root, denylist=denylist)
        scanned_count = len(selected)

    if findings:
        print(
            f"Privacy check failed with {len(findings)} finding(s):",
            file=sys.stderr,
        )
        for finding in findings:
            print(format_finding(finding), file=sys.stderr)
        return 1
    print(f"Privacy check passed: {scanned_count} file(s) scanned.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="optional files to scan instead of tracked files")
    arguments = parser.parse_args(argv)
    return run(arguments.paths)


if __name__ == "__main__":
    raise SystemExit(main())
