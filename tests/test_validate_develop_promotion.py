import json
import os
import sys
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from work_item_lifecycle import LifecycleState  # noqa: E402
from validate_develop_promotion import (  # noqa: E402
    DevelopPromotionValidationError,
    main,
    validate_event,
)

HEAD_SHA = "1" * 40
OTHER_SHA = "2" * 40
ISSUE_ID = "332"


def event(
    *,
    head_ref="ai/integration",
    base_ref="develop",
    head_sha=HEAD_SHA,
    body=None,
):
    return {
        "repository": {"full_name": "KenlikDev/aegis-engineering-os"},
        "pull_request": {
            "head": {
                "ref": head_ref,
                "sha": head_sha,
                "repo": {"full_name": "KenlikDev/aegis-engineering-os"},
            },
            "base": {
                "ref": base_ref,
                "repo": {"full_name": "KenlikDev/aegis-engineering-os"},
            },
            "body": (
                f"- Work item: #{ISSUE_ID}\n"
                f"- Verified source SHA: {HEAD_SHA}\n"
                if body is None
                else body
            ),
        }
    }


class DevelopPromotionValidationTests(unittest.TestCase):
    def _lookup(self, issue_id):
        self.assertEqual(ISSUE_ID, issue_id)
        return SimpleNamespace(
            id=ISSUE_ID,
            state=LifecycleState.INTEGRATION,
        )

    def test_accepts_matching_direct_develop_promotion(self):
        validate_event(event(), issue_lookup=self._lookup)

    def test_rejects_drifted_head(self):
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "head SHA does not match",
        ):
            validate_event(event(head_sha=OTHER_SHA), issue_lookup=self._lookup)

    def test_rejects_missing_marker(self):
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "exactly one owner-verified",
        ):
            validate_event(event(body="owner verification omitted\n"))

    def test_rejects_duplicate_markers(self):
        body = (
            f"- Work item: #{ISSUE_ID}\n"
            f"- Verified source SHA: {HEAD_SHA}\n"
            f"- Verified source SHA: {HEAD_SHA}\n"
        )
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "exactly one owner-verified",
        ):
            validate_event(event(body=body), issue_lookup=self._lookup)

    def test_rejects_non_integrated_work_item(self):
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "must be in integration lifecycle state",
        ):
            validate_event(
                event(),
                issue_lookup=lambda issue_id: SimpleNamespace(
                    id=issue_id,
                    state=LifecycleState.REVIEW,
                ),
            )

    def test_rejects_mismatched_work_item_identity(self):
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "identity does not match",
        ):
            validate_event(
                event(),
                issue_lookup=lambda issue_id: SimpleNamespace(
                    id="999",
                    state=__import__("work_item_lifecycle").LifecycleState.INTEGRATION,
                ),
            )

    def test_rejects_missing_work_item_lookup(self):
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "work-item lookup is required",
        ):
            validate_event(event())

    def test_ignores_other_pull_request_flows(self):
        validate_event(event(base_ref="ai/integration"), issue_lookup=self._lookup)
        validate_event(event(head_ref="ai/chore/123-example"), issue_lookup=self._lookup)

    def test_rejects_fork_origin(self):
        payload = event()
        payload["pull_request"]["head"]["repo"]["full_name"] = "attacker/example-fork"
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "must originate from the configured repository",
        ):
            validate_event(payload, issue_lookup=self._lookup)

    def test_rejects_malformed_head_sha(self):
        with self.assertRaisesRegex(
            DevelopPromotionValidationError,
            "malformed head SHA",
        ):
            validate_event(event(head_sha="not-a-sha"), issue_lookup=self._lookup)

    def test_cli_reads_event_payload(self):
        payload = event()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "event.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            old_argv = sys.argv
            try:
                sys.argv = ["validate_develop_promotion.py", str(path)]
                with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}):
                    with mock.patch(
                        "validate_develop_promotion._lookup_work_item",
                        return_value=self._lookup(ISSUE_ID),
                    ):
                        self.assertEqual(0, main())
            finally:
                sys.argv = old_argv

    def test_cli_fails_on_invalid_event_payload(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "event.json"
            path.write_text("[]", encoding="utf-8")
            old_argv = sys.argv
            try:
                sys.argv = ["validate_develop_promotion.py", str(path)]
                self.assertEqual(1, main())
            finally:
                sys.argv = old_argv


if __name__ == "__main__":
    unittest.main()
