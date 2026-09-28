import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_contract import EvidenceContractError, build_evidence, write_evidence  # noqa: E402


class EvidenceOutputSecurityTests(unittest.TestCase):
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
