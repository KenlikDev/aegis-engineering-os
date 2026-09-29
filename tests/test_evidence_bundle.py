import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_bundle import (  # noqa: E402
    EvidenceBundleError,
    build_evidence_bundle,
    read_and_validate_evidence_bundle,
    write_evidence_bundle,
)
from evidence_contract import (  # noqa: E402
    build_evidence,
    read_and_validate_evidence,
    write_evidence,
)


def _evidence(kind: str, subject: str):
    return build_evidence(
        {
            "schema_version": 1,
            "kind": kind,
            "source": "github:KenlikDev/aegis-engineering-os",
            "subject": subject,
            "revision": "7c2d2247abf2d4463a2167d20e7ab18a808a24ee",
            "observed_at": "2026-09-28T18:00:00Z",
            "status": "verified",
            "result": {"state": subject},
            "uncertainty": [],
            "references": ["https://github.com/KenlikDev/aegis-engineering-os"],
            "artifact_sha256": None,
        }
    )


class EvidenceBundleTests(unittest.TestCase):
    def _project(self):
        temp = tempfile.TemporaryDirectory()
        root = Path(temp.name)
        one = root / ".aegis" / "one.json"
        two = root / ".aegis" / "two.json"
        one.parent.mkdir(parents=True)
        write_evidence(_evidence("repository-state", "branch:ai/integration"), one)
        write_evidence(_evidence("release-readiness", "release:main"), two)
        self.addCleanup(temp.cleanup)
        return root, one, two

    def test_build_sorts_members_and_is_deterministic(self):
        root, one, two = self._project()
        first = build_evidence_bundle(root, "Readiness input set", [two, one])
        second = build_evidence_bundle(root, "Readiness input set", [one, two])
        self.assertEqual(first, second)
        self.assertEqual(
            tuple(sorted(first.members, key=lambda item: (item.evidence_id, item.path))),
            first.members,
        )

    def test_round_trip_validates_all_members(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        output = root / ".aegis" / "bundle.json"
        write_evidence_bundle(bundle, root, output)
        validated = read_and_validate_evidence_bundle(root, output)
        self.assertEqual(bundle, validated)
        self.assertEqual(bundle.members[0].evidence_id, read_and_validate_evidence(one).evidence_id)

    def test_tampered_member_blocks_validation(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        output = root / ".aegis" / "bundle.json"
        write_evidence_bundle(bundle, root, output)
        tampered = json.loads(one.read_text(encoding="utf-8"))
        tampered["result"]["state"] = "tampered"
        one.write_text(json.dumps(tampered, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceBundleError, "invalid"):
            read_and_validate_evidence_bundle(root, output)

    def test_missing_member_blocks_validation(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        output = root / ".aegis" / "bundle.json"
        write_evidence_bundle(bundle, root, output)
        two.unlink()
        with self.assertRaisesRegex(EvidenceBundleError, "does not exist"):
            read_and_validate_evidence_bundle(root, output)

    def test_duplicate_member_is_rejected(self):
        root, one, _ = self._project()
        with self.assertRaisesRegex(EvidenceBundleError, "Duplicate evidence ID"):
            build_evidence_bundle(root, "Readiness input set", [one, one])

    def test_path_escape_is_rejected(self):
        root, one, _ = self._project()
        outside = root.parent / "outside.json"
        outside.write_text(one.read_text(encoding="utf-8"), encoding="utf-8")
        self.addCleanup(lambda: outside.unlink(missing_ok=True))
        with self.assertRaisesRegex(EvidenceBundleError, "inside the project root"):
            build_evidence_bundle(root, "Readiness input set", [outside])

    def test_malformed_bundle_schema_is_rejected(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        output = root / ".aegis" / "bundle.json"
        write_evidence_bundle(bundle, root, output)
        malformed = json.loads(output.read_text(encoding="utf-8"))
        malformed["extra"] = True
        output.write_text(json.dumps(malformed), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceBundleError, "unknown keys"):
            read_and_validate_evidence_bundle(root, output)

    def test_bundle_hash_drift_is_rejected(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        output = root / ".aegis" / "bundle.json"
        write_evidence_bundle(bundle, root, output)
        malformed = json.loads(output.read_text(encoding="utf-8"))
        malformed["purpose"] = "Changed purpose"
        output.write_text(json.dumps(malformed), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceBundleError, "identity hash"):
            read_and_validate_evidence_bundle(root, output)

    def test_unsorted_members_are_rejected_on_read(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        output = root / ".aegis" / "bundle.json"
        write_evidence_bundle(bundle, root, output)
        payload = json.loads(output.read_text(encoding="utf-8"))
        payload["members"].reverse()
        payload["bundle_id"] = "0" * 64
        output.write_text(json.dumps(payload), encoding="utf-8")
        with self.assertRaisesRegex(EvidenceBundleError, "sorted"):
            read_and_validate_evidence_bundle(root, output)

    def test_write_rejects_member_path_as_output(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        with self.assertRaisesRegex(EvidenceBundleError, "must not overwrite"):
            write_evidence_bundle(bundle, root, one)

    def test_write_rejects_symlinked_output(self):
        root, one, two = self._project()
        bundle = build_evidence_bundle(root, "Readiness input set", [one, two])
        target = root / ".aegis" / "bundle-target.json"
        target.write_text("preserve\n", encoding="utf-8")
        output = root / ".aegis" / "bundle.json"
        try:
            output.symlink_to(target)
        except OSError as exc:
            self.skipTest(f"symbolic links unavailable: {exc}")

        with self.assertRaisesRegex(EvidenceBundleError, "symbolic link"):
            write_evidence_bundle(bundle, root, output)

        self.assertEqual("preserve\n", target.read_text(encoding="utf-8"))
    def test_existing_evidence_remains_independently_valid(self):
        root, one, _ = self._project()
        self.assertEqual(
            read_and_validate_evidence(one),
            read_and_validate_evidence(one),
        )


if __name__ == "__main__":
    unittest.main()
