import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_contract import (  # noqa: E402
    EvidenceContractError,
    EvidenceRecord,
    build_evidence,
    write_evidence,
)


class EvidenceOutputSecurityTests(unittest.TestCase):
    def test_atomic_writer_replaces_destination_if_it_becomes_symlink_during_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "protected.json"
            output = root / "evidence.json"
            target.write_text("protected\n", encoding="utf-8")

            payload = {"status": "verified"}
            real_replace = os.replace

            def race_replace(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                output.symlink_to(target)
                return real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            from evidence_contract import write_json_atomically

            with patch("evidence_contract.os.replace", side_effect=race_replace):
                write_json_atomically(payload, output)

            self.assertEqual("protected\n", target.read_text(encoding="utf-8"))
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))
            self.assertFalse(output.is_symlink())


    def test_atomic_writer_is_anchored_when_parent_directory_becomes_symlink(self) -> None:
        if os.name != "posix":
            self.skipTest("directory-FD anchoring is only available on POSIX.")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            parent = root / "output"
            moved_parent = root / "output-original"
            external = root / "external"
            parent.mkdir()
            external.mkdir()
            output = parent / "evidence.json"
            payload = {"status": "verified"}

            real_replace = os.replace
            race_triggered = False

            def race_replace(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                nonlocal race_triggered
                parent.rename(moved_parent)
                parent.symlink_to(external, target_is_directory=True)
                race_triggered = True
                return real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            from evidence_contract import write_json_atomically

            with patch("evidence_contract.os.replace", side_effect=race_replace):
                write_json_atomically(payload, output)

            self.assertTrue(race_triggered)
            self.assertFalse((external / "evidence.json").exists())
            self.assertEqual(
                payload,
                json.loads((moved_parent / "evidence.json").read_text(encoding="utf-8")),
            )
            self.assertTrue(parent.is_symlink())


    def test_atomic_writer_rejects_symlinked_parent_directory(self) -> None:
        if os.name != "posix":
            self.skipTest("directory-FD no-follow support is only available on POSIX.")

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            external = root / "external"
            external.mkdir()
            parent = root / "output"
            parent.symlink_to(external, target_is_directory=True)
            output = parent / "evidence.json"

            from evidence_contract import write_json_atomically

            with self.assertRaisesRegex(
                EvidenceContractError,
                "securely open JSON output directory",
            ):
                write_json_atomically({"status": "verified"}, output)

            self.assertFalse((external / "evidence.json").exists())


    def test_atomic_byte_writer_replaces_destination_symlink_without_following_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            external = root / "external.txt"
            output = root / "output.txt"
            external.write_text("protected\n", encoding="utf-8")

            real_replace = os.replace

            def race_replace(
                source,
                destination,
                *,
                src_dir_fd=None,
                dst_dir_fd=None,
            ):
                output.symlink_to(external)
                return real_replace(
                    source,
                    destination,
                    src_dir_fd=src_dir_fd,
                    dst_dir_fd=dst_dir_fd,
                )

            with patch("evidence_contract.os.replace", side_effect=race_replace):
                from evidence_contract import write_bytes_atomically

                write_bytes_atomically(b"replacement\n", output)

            self.assertEqual("protected\n", external.read_text(encoding="utf-8"))
            self.assertEqual("replacement\n", output.read_text(encoding="utf-8"))
            self.assertFalse(output.is_symlink())

    def test_build_evidence_rejects_oversized_canonical_record(self) -> None:
        large_result = {"items": ["x" * 4096 for _ in range(20)]}

        with self.assertRaisesRegex(
            EvidenceContractError,
            r"Canonical evidence payload exceeds the 65536-byte limit",
        ):
            build_evidence(
                {
                    "schema_version": 1,
                    "kind": "testing",
                    "source": "aegis:test",
                    "subject": "large",
                    "revision": None,
                    "observed_at": "2026-09-29T00:00:00Z",
                    "status": "verified",
                    "result": large_result,
                    "uncertainty": [],
                    "references": [],
                    "artifact_sha256": None,
                }
            )

    def test_write_evidence_rejects_oversized_record_before_persistence(self) -> None:
        record = EvidenceRecord(
            schema_version=1,
            evidence_id="0" * 64,
            kind="testing",
            source="aegis:test",
            subject="large",
            revision=None,
            observed_at="2026-09-29T00:00:00Z",
            status="verified",
            result={"items": ["x" * 4096 for _ in range(20)]},
            uncertainty=(),
            references=(),
            artifact_sha256=None,
            evidence_sha256="0" * 64,
        )

        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "evidence.json"
            with self.assertRaisesRegex(
                EvidenceContractError,
                r"Canonical evidence record exceeds the 65536-byte limit",
            ):
                write_evidence(record, output)

            self.assertFalse(output.exists())

    def test_write_evidence_rejects_symlink_output(self) -> None:
        record = build_evidence(
            {
                "schema_version": 1,
                "kind": "testing",
                "source": "aegis:test",
                "subject": "security",
                "revision": None,
                "observed_at": "2026-09-29T00:00:00Z",
                "status": "verified",
                "result": {"state": "passed"},
                "uncertainty": [],
                "references": [],
                "artifact_sha256": None,
            }
        )

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            protected = root / "protected.json"
            protected.write_text("protected\n", encoding="utf-8")
            output = root / "output.json"
            output.symlink_to(protected)

            with self.assertRaisesRegex(
                EvidenceContractError,
                "must not be a symbolic link",
            ):
                write_evidence(record, output)

            self.assertEqual(
                "protected\n",
                protected.read_text(encoding="utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
