import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from knowledge_gap import (  # noqa: E402
    KnowledgeGapError,
    create_candidate,
    reject_candidate,
    validate_candidate,
)


class KnowledgeGapTests(unittest.TestCase):
    def test_create_candidate_persists_candidate_state_and_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            record = create_candidate(
                scope="global",
                capability="database migration safety",
                problem="Aegis lacks guidance for migration rollback verification.",
                proposed_change="Add a candidate skill after validating a focused rollback scenario.",
                references=["https://docs.example.test/migrations"],
                store_root=directory,
                candidate_id="11111111-1111-4111-8111-111111111111",
            )
            path = Path(directory) / "11111111-1111-4111-8111-111111111111.json"
            payload = json.loads(path.read_text(encoding="utf-8"))

            self.assertEqual("candidate", record.state)
            self.assertEqual("candidate", payload["state"])
            self.assertTrue(payload["candidate"]["candidate_sha256"])
            self.assertIsNone(payload["validation"])

    def test_validate_requires_evidence_and_moves_to_validated(self):
        with tempfile.TemporaryDirectory() as directory:
            record = create_candidate(
                scope="project",
                capability="project deployment topology",
                problem="The project topology is not documented in the reusable knowledge base.",
                proposed_change="Create project-local deployment guidance after verification.",
                references=["https://docs.example.test/project/deployment"],
                store_root=directory,
                candidate_id="22222222-2222-4222-8222-222222222222",
            )
            path = Path(directory) / "22222222-2222-4222-8222-222222222222.json"

            with self.assertRaisesRegex(KnowledgeGapError, "At least one validation evidence"):
                validate_candidate(path, scenario="focused scenario", evidence_refs=[])

            validated = validate_candidate(
                path,
                scenario="deploy to staging and verify rollback path",
                evidence_refs=["https://ci.example.test/runs/42"],
            )
            self.assertEqual("validated", validated.state)
            self.assertIsNotNone(validated.validation)
            self.assertEqual("passed", validated.validation["outcome"])

    def test_validation_preserves_original_candidate_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            create_candidate(
                scope="global",
                capability="safe retries",
                problem="Retry guidance is missing.",
                proposed_change="Document bounded retry behavior.",
                references=["https://docs.example.test/retries"],
                store_root=directory,
                candidate_id="33333333-3333-4333-8333-333333333333",
            )
            path = Path(directory) / "33333333-3333-4333-8333-333333333333.json"
            before = json.loads(path.read_text(encoding="utf-8"))["candidate"]["candidate_sha256"]

            validate_candidate(
                path,
                scenario="run one deterministic retry scenario",
                evidence_refs=["https://ci.example.test/runs/43"],
            )
            after = json.loads(path.read_text(encoding="utf-8"))["candidate"]["candidate_sha256"]
            self.assertEqual(before, after)

    def test_reject_candidate_preserves_existing_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            create_candidate(
                scope="global",
                capability="safe retries",
                problem="Retry guidance is missing.",
                proposed_change="Document bounded retry behavior.",
                references=["https://docs.example.test/retries"],
                store_root=directory,
                candidate_id="44444444-4444-4444-8444-444444444444",
            )
            path = Path(directory) / "44444444-4444-4444-8444-444444444444.json"

            validate_candidate(
                path,
                scenario="run one deterministic retry scenario",
                evidence_refs=["https://ci.example.test/runs/44"],
            )
            rejected = reject_candidate(path, reason="Scenario does not generalize safely.")
            self.assertEqual("rejected", rejected.state)
            self.assertIsNotNone(rejected.validation)
            self.assertEqual(
                ["candidate", "validated", "rejected"],
                [transition["to"] for transition in rejected.transitions],
            )

    def test_rejects_tampered_candidate_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            create_candidate(
                scope="global",
                capability="safe retries",
                problem="Retry guidance is missing.",
                proposed_change="Document bounded retry behavior.",
                references=["https://docs.example.test/retries"],
                store_root=directory,
                candidate_id="55555555-5555-4555-8555-555555555555",
            )
            path = Path(directory) / "55555555-5555-4555-8555-555555555555.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["candidate"]["problem"] = "tampered"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(KnowledgeGapError, "provenance hash"):
                validate_candidate(
                    path,
                    scenario="unused",
                    evidence_refs=["https://ci.example.test/runs/45"],
                )

    def test_rejects_secret_like_candidate_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(KnowledgeGapError, "secret-like value"):
                create_candidate(
                    scope="global",
                    capability="unsafe secret handling",
                    problem="contains ghp_SUPERSECRET123",
                    proposed_change="Do not persist credentials.",
                    references=["https://docs.example.test/security"],
                    store_root=directory,
                )

    def test_rejects_non_https_reference(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(KnowledgeGapError, "HTTPS URLs"):
                create_candidate(
                    scope="global",
                    capability="safe retries",
                    problem="Retry guidance is missing.",
                    proposed_change="Document bounded retry behavior.",
                    references=["file:///tmp/private.txt"],
                    store_root=directory,
                )

    def test_rejects_tampered_validation_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            create_candidate(
                scope="global",
                capability="tamper detection",
                problem="Validation records must not be silently altered.",
                proposed_change="Hash the serialized validation evidence.",
                references=["https://docs.example.test/knowledge"],
                store_root=directory,
                candidate_id="88888888-8888-4888-8888-888888888888",
            )
            path = Path(directory) / "88888888-8888-4888-8888-888888888888.json"
            validate_candidate(
                path,
                scenario="run tamper detection scenario",
                evidence_refs=["https://ci.example.test/runs/47"],
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["validation"]["scenario"] = "tampered"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(KnowledgeGapError, "evidence hash"):
                reject_candidate(path, reason="should fail closed")


    def test_redacts_secret_like_validation_data(self):
        with tempfile.TemporaryDirectory() as directory:
            create_candidate(
                scope="global",
                capability="secret-safe evidence",
                problem="Evidence must remain safe.",
                proposed_change="Record only redacted validation evidence.",
                references=["https://docs.example.test/evidence"],
                store_root=directory,
                candidate_id="66666666-6666-4666-8666-666666666666",
            )
            path = Path(directory) / "66666666-6666-4666-8666-666666666666.json"
            validate_candidate(
                path,
                scenario="check sanitized output ghp_SUPERSECRET123",
                evidence_refs=["https://ci.example.test/runs/46"],
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            serialized = json.dumps(payload)
            self.assertNotIn("ghp_SUPERSECRET123", serialized)
            self.assertIn("[REDACTED]", serialized)

            rejected = reject_candidate(path, reason="validated evidence no longer applies.")
            self.assertEqual("rejected", rejected.state)

    def test_rejects_activation_like_state_from_disk(self):
        with tempfile.TemporaryDirectory() as directory:
            record = create_candidate(
                scope="global",
                capability="activation control",
                problem="Active knowledge must not be replaced automatically.",
                proposed_change="Keep activation outside the candidate registry.",
                references=["https://docs.example.test/knowledge"],
                store_root=directory,
                candidate_id="77777777-7777-4777-8777-777777777777",
            )
            path = Path(directory) / f"{record.candidate.candidate_id}.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["state"] = "active"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(KnowledgeGapError, "invalid state"):
                reject_candidate(path, reason="should never happen")


if __name__ == "__main__":
    unittest.main()
