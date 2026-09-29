import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_contract import EvidenceContractError, build_evidence, write_evidence  # noqa: E402


class EvidenceOutputSecurityTests(unittest.TestCase):
    def test_atomic_writer_replaces_destination_if_it_becomes_symlink_during_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / "protected.json"
            output = root / "evidence.json"
            target.write_text("protected\n", encoding="utf-8")

            payload = {"status": "verified"}
            real_replace = os.replace

            def race_replace(source, destination):  # noqa: ANN001
                output.symlink_to(target)
                real_replace(source, destination)

            from evidence_contract import write_json_atomically

            with patch("evidence_contract.os.replace", side_effect=race_replace):
                write_json_atomically(payload, output)

            self.assertEqual("protected\n", target.read_text(encoding="utf-8"))
            self.assertEqual(payload, json.loads(output.read_text(encoding="utf-8")))
            self.assertFalse(output.is_symlink())

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
