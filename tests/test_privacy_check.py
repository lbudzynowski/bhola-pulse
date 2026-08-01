from __future__ import annotations

import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "privacy-check.py"
SPEC = importlib.util.spec_from_file_location("privacy_check", SCRIPT_PATH)
assert SPEC is not None and SPEC.loader is not None
privacy_check = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = privacy_check
SPEC.loader.exec_module(privacy_check)


class PrivacyCheckTests(unittest.TestCase):
    def scan(self, name: str, content: str):
        return privacy_check.scan_bytes(name, content.encode("utf-8"))

    def clean_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.pop(privacy_check.DENYLIST_ENV, None)
        return environment

    @staticmethod
    def png_chunk(chunk_type: bytes, data: bytes) -> bytes:
        checksum = zlib.crc32(chunk_type)
        checksum = zlib.crc32(data, checksum) & 0xFFFFFFFF
        return (
            struct.pack(">I", len(data))
            + chunk_type
            + data
            + struct.pack(">I", checksum)
        )

    @classmethod
    def minimal_png(
        cls,
        width: int,
        height: int,
        *,
        extra_chunks: tuple[tuple[bytes, bytes], ...] = (),
        include_idat: bool = True,
        trailing: bytes = b"",
    ) -> bytes:
        ihdr = struct.pack(">IIBBBBB", width, height, 8, 0, 0, 0, 0)
        chunks = [cls.png_chunk(b"IHDR", ihdr)]
        chunks.extend(cls.png_chunk(kind, value) for kind, value in extra_chunks)
        if include_idat:
            scanlines = (b"\x00" + (b"\x00" * width)) * height
            chunks.append(cls.png_chunk(b"IDAT", zlib.compress(scanlines)))
        chunks.append(cls.png_chunk(b"IEND", b""))
        return privacy_check.PNG_SIGNATURE + b"".join(chunks) + trailing

    def test_detects_linux_home_path(self) -> None:
        value = "/" + "home/example/Projects/private"
        findings = self.scan("sample.txt", value)
        self.assertIn("absolute_home_path", {item.category for item in findings})

    def test_detects_windows_home_path(self) -> None:
        value = "C:" + "\\Users\\example\\Projects\\private"
        findings = self.scan("sample.txt", value)
        self.assertIn("absolute_home_path", {item.category for item in findings})

    def test_detects_key_or_token(self) -> None:
        value = "ghp_" + "A" * 32
        findings = self.scan("sample.txt", value)
        self.assertIn("credential_token", {item.category for item in findings})

    def test_detects_private_key_header(self) -> None:
        value = "-----BEGIN " + "PRIVATE KEY-----"
        findings = self.scan("sample.txt", value)
        self.assertIn("private_key", {item.category for item in findings})

    def test_allows_portable_home_path(self) -> None:
        self.assertEqual([], self.scan("sample.txt", "$HOME/Projects/bhola-pulse"))

    def test_allows_public_github_links(self) -> None:
        value = "https://github.com/example/project/issues/1"
        self.assertEqual([], self.scan("sample.txt", value))

    def test_redacts_detected_value(self) -> None:
        value = "sk-" + "A" * 30
        finding = self.scan("sample.txt", value)[0]
        rendered = privacy_check.format_finding(finding)
        self.assertNotIn(value, rendered)
        self.assertIn("<redacted:", rendered)

    def test_scans_suspicious_filename(self) -> None:
        findings = self.scan("credentials.env", "placeholder")
        self.assertIn("suspicious_filename", {item.category for item in findings})

    def test_returns_nonzero_for_finding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "sample.txt"
            sample.write_text("token = " + "A" * 24, encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(sample)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
            )
        self.assertEqual(1, completed.returncode)
        self.assertNotIn("A" * 24, completed.stderr)

    def test_returns_zero_for_clean_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "sample.txt"
            sample.write_text("$HOME/Projects/bhola-pulse\n", encoding="utf-8")
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(sample)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=self.clean_environment(),
            )
        self.assertEqual(0, completed.returncode)
        self.assertEqual("", completed.stderr)

    def test_detects_value_from_temporary_denylist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            denylist_path = Path(directory) / "denylist.txt"
            denylist_path.write_text("MarbleBeacon42\n", encoding="utf-8")
            denylist = privacy_check.load_denylist(
                {privacy_check.DENYLIST_ENV: str(denylist_path)}
            )
        findings = privacy_check.scan_bytes(
            "sample.txt",
            b"prefix MarbleBeacon42 suffix",
            denylist=denylist,
        )
        self.assertIn("private_denylist", {item.category for item in findings})

    def test_denylist_is_case_insensitive_for_names_and_content(self) -> None:
        denylist = ("NeutralMarker",)
        content_findings = privacy_check.scan_bytes(
            "sample.txt",
            b"neutralmarker",
            denylist=denylist,
        )
        name_findings = privacy_check.scan_bytes(
            "NEUTRALMARKER.txt",
            b"safe",
            denylist=denylist,
        )
        self.assertIn("private_denylist", {item.category for item in content_findings})
        self.assertIn("private_denylist", {item.category for item in name_findings})

    def test_denylist_output_redacts_value_and_path(self) -> None:
        value = "CopperLantern77"
        finding = privacy_check.scan_bytes(
            "sensitive-name.txt",
            value.encode("utf-8"),
            denylist=(value,),
        )[0]
        rendered = privacy_check.format_finding(finding)
        self.assertNotIn(value, rendered)
        self.assertNotIn("sensitive-name.txt", rendered)
        self.assertIn("private_denylist", rendered)
        self.assertIn("<redacted:", rendered)

    def test_denylist_ignores_comments_and_blank_lines(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            denylist_path = Path(directory) / "denylist.txt"
            denylist_path.write_text(
                "\n# local-only values\n\nNeutralMarker\n",
                encoding="utf-8",
            )
            denylist = privacy_check.load_denylist(
                {privacy_check.DENYLIST_ENV: str(denylist_path)}
            )
        self.assertEqual(("NeutralMarker",), denylist)

    def test_denylist_rejects_short_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            denylist_path = Path(directory) / "denylist.txt"
            denylist_path.write_text("abc\n", encoding="utf-8")
            with self.assertRaises(privacy_check.DenylistConfigurationError):
                privacy_check.load_denylist(
                    {privacy_check.DENYLIST_ENV: str(denylist_path)}
                )

    def test_missing_denylist_fails_closed_without_printing_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            sample = Path(directory) / "sample.txt"
            sample.write_text("safe\n", encoding="utf-8")
            missing = Path(directory) / "missing-denylist.txt"
            environment = self.clean_environment()
            environment[privacy_check.DENYLIST_ENV] = str(missing)
            completed = subprocess.run(
                [sys.executable, str(SCRIPT_PATH), str(sample)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                check=False,
                env=environment,
            )
        self.assertEqual(2, completed.returncode)
        self.assertNotIn(str(missing), completed.stderr)
        self.assertIn("privacy_denylist_error", completed.stderr)

    def test_runs_cleanly_without_configured_denylist(self) -> None:
        self.assertEqual((), privacy_check.load_denylist({}))
        self.assertEqual([], privacy_check.scan_bytes("sample.txt", b"NeutralMarker"))

    def test_allows_only_approved_png_paths_with_expected_dimensions(self) -> None:
        self.assertEqual(
            {
                "docs/images/large-sharp.png": (958, 721),
                "docs/images/nerd-mode.png": (958, 721),
            },
            privacy_check.APPROVED_PNG_DIMENSIONS,
        )
        for path, dimensions in privacy_check.APPROVED_PNG_DIMENSIONS.items():
            with self.subTest(path=path):
                data = self.minimal_png(*dimensions)
                self.assertEqual([], privacy_check.scan_bytes(path, data))

    def test_rejects_identical_png_at_another_path(self) -> None:
        data = self.minimal_png(958, 721)
        findings = privacy_check.scan_bytes("docs/images/other.png", data)
        self.assertIn("binary_file_unscanned", {item.category for item in findings})

    def test_rejects_approved_png_with_invalid_signature(self) -> None:
        data = b"invalid!" + self.minimal_png(958, 721)[8:]
        findings = privacy_check.scan_bytes(
            "docs/images/large-sharp.png",
            data,
        )
        self.assertIn(
            "approved_png_invalid_signature",
            {item.category for item in findings},
        )

    def test_rejects_approved_png_with_invalid_crc(self) -> None:
        data = bytearray(self.minimal_png(958, 721))
        ihdr_crc_offset = len(privacy_check.PNG_SIGNATURE) + 4 + 4 + 13
        data[ihdr_crc_offset] ^= 1
        findings = privacy_check.scan_bytes(
            "docs/images/large-sharp.png",
            bytes(data),
        )
        self.assertIn("approved_png_invalid_crc", {item.category for item in findings})

    def test_rejects_approved_png_with_wrong_dimensions(self) -> None:
        data = self.minimal_png(957, 721)
        findings = privacy_check.scan_bytes(
            "docs/images/large-sharp.png",
            data,
        )
        self.assertIn(
            "approved_png_unexpected_dimensions",
            {item.category for item in findings},
        )

    def test_rejects_approved_png_with_metadata_chunk(self) -> None:
        data = self.minimal_png(
            958,
            721,
            extra_chunks=((b"tEXt", b"Comment\x00not allowed"),),
        )
        findings = privacy_check.scan_bytes(
            "docs/images/nerd-mode.png",
            data,
        )
        self.assertIn(
            "approved_png_unexpected_chunk",
            {item.category for item in findings},
        )

    def test_rejects_approved_png_with_trailing_data(self) -> None:
        data = self.minimal_png(958, 721, trailing=b"unexpected")
        findings = privacy_check.scan_bytes(
            "docs/images/nerd-mode.png",
            data,
        )
        self.assertIn(
            "approved_png_trailing_data",
            {item.category for item in findings},
        )

    def test_rejects_approved_png_without_idat(self) -> None:
        data = self.minimal_png(958, 721, include_idat=False)
        findings = privacy_check.scan_bytes(
            "docs/images/nerd-mode.png",
            data,
        )
        self.assertIn("approved_png_missing_idat", {item.category for item in findings})

    def test_rejects_empty_or_oversized_approved_png(self) -> None:
        for data in (b"", b"\x00" * (privacy_check.MAX_APPROVED_PNG_SIZE + 1)):
            with self.subTest(size=len(data)):
                findings = privacy_check.scan_bytes(
                    "docs/images/large-sharp.png",
                    data,
                )
                self.assertIn(
                    "approved_png_invalid_size",
                    {item.category for item in findings},
                )

    def test_scanner_source_passes_its_own_scan(self) -> None:
        findings = privacy_check.scan_bytes(
            "scripts/privacy-check.py",
            SCRIPT_PATH.read_bytes(),
        )
        self.assertEqual([], findings)


if __name__ == "__main__":
    unittest.main()
