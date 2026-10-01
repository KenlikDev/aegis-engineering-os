import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_contract import EvidenceContractError, build_evidence, load_json_object, read_and_validate_evidence  # noqa: E402
from state_verification import record_state_evidence  # noqa: E402


def _payload(observed_at="2026-09-28T18:00:00Z"):
    return {
        "schema_version": 1,
        "kind": "repository-state",
        "source": "github:KenlikDev/aegis-engineering-os",
        "subject": "branch:ai/integration",
        "revision": "2e8a617e0b678226ab88066437700784053c972d",
        "observed_at": observed_at,
        "status": "verified",
        "result": {
            "branch_exists": True,
            "head": "2e8a617e0b678226ab88066437700784053c972d",
        },
        "uncertainty": [],
        "references": [
            "https://github.com/KenlikDev/aegis-engineering-os"
        ],
        "artifact_sha256": None,
    }


class EvidenceContractTests(unittest.TestCase):
    def test_builds_self_hashed_record(self):
        record = build_evidence(_payload())
        self.assertEqual(record.evidence_id, record.evidence_sha256)
        self.assertEqual(64, len(record.evidence_sha256))
        self.assertEqual("2026-09-28T18:00:00Z", record.observed_at)

    def test_timestamp_normalization_is_deterministic(self):
        first = build_evidence(_payload("2026-09-28T20:00:00+02:00"))
        second = build_evidence(_payload("2026-09-28T18:00:00Z"))
        self.assertEqual(first, second)

    def test_hash_changes_when_observation_changes(self):
        original = build_evidence(_payload())
        changed = _payload()
        changed["result"]["branch_exists"] = False
        changed["observed_at"] = "2026-09-28T18:00:01Z"
        replacement = build_evidence(changed)
        self.assertNotEqual(original.evidence_sha256, replacement.evidence_sha256)

    def test_hash_drift_is_rejected(self):
        record = build_evidence(_payload())
        tampered = {
            "schema_version": record.schema_version,
            "evidence_id": record.evidence_id,
            "kind": record.kind,
            "source": record.source,
            "subject": record.subject,
            "revision": record.revision,
            "observed_at": record.observed_at,
            "status": record.status,
            "result": {**record.result, "branch_exists": False},
            "uncertainty": list(record.uncertainty),
            "references": list(record.references),
            "artifact_sha256": record.artifact_sha256,
            "evidence_sha256": record.evidence_sha256,
        }
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "evidence.json"
            path.write_text(
                json.dumps(tampered, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(EvidenceContractError, "identity hash"):
                read_and_validate_evidence(path)

    def test_unknown_schema_key_is_rejected(self):
        payload = _payload()
        payload["extra"] = True
        with self.assertRaisesRegex(EvidenceContractError, "unknown keys"):
            build_evidence(payload)

    def test_invalid_timestamp_is_rejected(self):
        payload = _payload("2026-09-28 18:00:00")
        with self.assertRaisesRegex(EvidenceContractError, "timezone"):
            build_evidence(payload)

    def test_secret_like_result_key_is_rejected(self):
        payload = _payload()
        payload["result"] = {"access_token": "do-not-record"}
        with self.assertRaisesRegex(EvidenceContractError, "secret-like"):
            build_evidence(payload)

    def test_secret_like_result_value_is_rejected(self):
        payload = _payload()
        payload["result"] = {"message": "Bearer abcdefghijklmnopqrstuvwxyz"}
        with self.assertRaisesRegex(EvidenceContractError, "credential-like"):
            build_evidence(payload)

    def test_non_https_reference_is_rejected(self):
        payload = _payload()
        payload["references"] = ["http://example.com/evidence"]
        with self.assertRaisesRegex(EvidenceContractError, "HTTPS"):
            build_evidence(payload)

    def test_duplicate_json_keys_are_rejected(self):
        raw = (
            '{"schema_version":1,"schema_version":1,'
            '"kind":"repository-state"}'
        )
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "input.json"
            path.write_text(raw, encoding="utf-8")
            with self.assertRaisesRegex(EvidenceContractError, "Duplicate JSON key"):
                load_json_object(path)

    def test_recording_rejects_symlinked_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "state.json"
            target = root / "target.json"
            output = root / "evidence.json"
            input_path.write_text(json.dumps(_payload()), encoding="utf-8")
            target.write_text("preserve\n", encoding="utf-8")
            try:
                output.symlink_to(target)
            except OSError as exc:
                self.skipTest(f"symbolic links unavailable: {exc}")

            with self.assertRaisesRegex(EvidenceContractError, "symbolic link"):
                record_state_evidence(input_path, output)

            self.assertEqual("preserve\n", target.read_text(encoding="utf-8"))

    def test_recording_preserves_input_and_validates_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            input_path = root / "state.json"
            output_path = root / "evidence.json"
            input_path.write_text(
                json.dumps(_payload(), indent=2),
                encoding="utf-8",
            )
            before = input_path.read_bytes()

            record = record_state_evidence(input_path, output_path)

            self.assertEqual(before, input_path.read_bytes())
            validated = read_and_validate_evidence(output_path)
            self.assertEqual(record, validated)

    def test_input_and_output_must_differ(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "state.json"
            path.write_text(json.dumps(_payload()), encoding="utf-8")
            with self.assertRaisesRegex(EvidenceContractError, "must differ"):
                record_state_evidence(path, path)

    def test_artifact_sha256_is_validated(self):
        payload = _payload()
        payload["artifact_sha256"] = "a" * 64
        self.assertEqual("a" * 64, build_evidence(payload).artifact_sha256)


if __name__ == "__main__":
    unittest.main()
