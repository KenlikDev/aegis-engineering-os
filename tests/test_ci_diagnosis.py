import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from ci_diagnosis import (  # noqa: E402
    CIDiagnosisError,
    DiagnosticReport,
    JobSnapshot,
    WorkflowRunSnapshot,
    diagnose,
    main,
    _redact,
    _bounded_excerpt,
)


REPOSITORY = "KenlikDev/aegis-engineering-os"
RUN = WorkflowRunSnapshot(
    repository=REPOSITORY,
    run_id=101,
    name="Aegis Validation",
    workflow_path=".github/workflows/validate.yml",
    event="pull_request",
    status="completed",
    conclusion="failure",
    head_branch="ai/feature/test",
    head_sha="1" * 40,
    url="https://github.com/KenlikDev/aegis-engineering-os/actions/runs/101",
)


class FakeProvider:
    def __init__(self, *, repository=REPOSITORY, run=RUN, jobs=None, logs=None):
        self.repository = repository
        self.run = run
        self.jobs = jobs or []
        self.logs = logs or {}

    def get_run(self, run_id):
        if run_id != self.run.run_id:
            raise AssertionError("unexpected run id")
        return self.run

    def latest_run(self, workflow, branch=None):
        return self.run

    def list_jobs(self, run_id):
        return list(self.jobs)

    def get_job_log(self, job_id):
        return self.logs[job_id]


class CIDiagnosisTests(unittest.TestCase):

    def test_cli_can_emit_canonical_evidence(self):
        success_run = WorkflowRunSnapshot(
            repository=REPOSITORY,
            run_id=101,
            name="Aegis Validation",
            workflow_path=".github/workflows/validate.yml",
            event="pull_request",
            status="completed",
            conclusion="success",
            head_branch="ai/integration",
            head_sha="1" * 40,
            url="https://github.com/example/actions/runs/101",
        )
        provider = FakeProvider(run=success_run, jobs=[], logs={})

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "ci-evidence.json"
            argv = [
                "ci_diagnosis.py",
                REPOSITORY,
                "--run-id",
                "101",
                "--canonical-evidence-output",
                str(output),
            ]
            stdout = io.StringIO()

            with (
                patch("ci_diagnosis.GitHubCIDiagnosisProvider", return_value=provider),
                patch.dict(os.environ, {"GITHUB_TOKEN": "test-token"}),
                patch.object(sys, "argv", argv),
                patch("sys.stdout", stdout),
            ):
                result = main()

            self.assertEqual(0, result)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual("ci-diagnosis", payload["kind"])
            self.assertEqual("verified", payload["status"])
            self.assertEqual("1" * 40, payload["revision"])
            self.assertEqual("workflow-run:101", payload["subject"])

    def test_failed_step_is_exposed_and_classified(self):
        job = JobSnapshot(
            job_id=10,
            name="Validate Aegis",
            status="completed",
            conclusion="failure",
            url="https://github.com/example/runs/10",
            failed_steps=("Run policy tests",),
        )
        provider = FakeProvider(
            jobs=[job],
            logs={10: "Traceback (most recent call last)\nFAILED (failures=1)"},
        )

        report = diagnose(provider, 101)

        self.assertIsInstance(report, DiagnosticReport)
        self.assertEqual("diagnosed", report.status)
        self.assertEqual(1, len(report.findings))
        self.assertEqual("Run policy tests", report.findings[0].step)
        self.assertEqual("test-failure", report.findings[0].category)
        self.assertTrue(report.findings[0].actionable)

    def test_exact_failed_step_takes_precedence_over_log_mentions(self):
        job = JobSnapshot(
            job_id=13,
            name="Validate Aegis",
            status="completed",
            conclusion="failure",
            url="https://github.com/example/runs/13",
            failed_steps=("Run policy tests",),
        )
        provider = FakeProvider(
            jobs=[job],
            logs={
                13: "security review is not relevant here; "
                "FAILED (failures=1)"
            },
        )

        report = diagnose(provider, 101)

        self.assertEqual("test-failure", report.findings[0].category)
        self.assertEqual("Run policy tests", report.findings[0].step)

    def test_unknown_failure_is_inconclusive(self):
        job = JobSnapshot(
            job_id=11,
            name="Unknown",
            status="completed",
            conclusion="failure",
            url="https://github.com/example/runs/11",
        )
        provider = FakeProvider(
            jobs=[job],
            logs={11: "some unexpected failure"},
        )

        report = diagnose(provider, 101)

        self.assertEqual("inconclusive", report.status)
        self.assertFalse(report.actionable)
        self.assertEqual("unknown", report.findings[0].category)

    def test_successful_run_is_healthy_and_does_not_read_logs(self):
        run = WorkflowRunSnapshot(
            repository=RUN.repository,
            run_id=RUN.run_id,
            name=RUN.name,
            workflow_path=RUN.workflow_path,
            event=RUN.event,
            status="completed",
            conclusion="success",
            head_branch=RUN.head_branch,
            head_sha=RUN.head_sha,
            url=RUN.url,
        )
        provider = FakeProvider(
            run=run,
            jobs=[
                JobSnapshot(
                    job_id=12,
                    name="Successful",
                    status="completed",
                    conclusion="success",
                    url="https://github.com/example/runs/12",
                )
            ],
            logs={},
        )

        report = diagnose(provider, 101)

        self.assertEqual("healthy", report.status)
        self.assertEqual(0, len(report.findings))

    def test_repository_identity_mismatch_fails_closed(self):
        provider = FakeProvider(repository="other/repository")
        with self.assertRaisesRegex(CIDiagnosisError, "repository"):
            diagnose(provider, 101)

    def test_log_evidence_is_bounded_and_redacted(self):
        secret = "ghp_SUPERSECRET1234567890"
        text = "token: TOPSECRET\n" + ("x" * 500) + secret
        bounded = _bounded_excerpt(text, limit=100)
        self.assertLessEqual(len(bounded), 100)
        self.assertNotIn(secret, bounded)
        self.assertIn("[REDACTED]", _redact(text))


    def test_http_job_log_download_is_bounded(self):
        from ci_diagnosis import GitHubCIDiagnosisProvider, MAX_LOG_DOWNLOAD_BYTES

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, size=-1):
                self.requested_size = size
                return b"x" * (MAX_LOG_DOWNLOAD_BYTES + 1)

        response = Response()
        provider = GitHubCIDiagnosisProvider(
            REPOSITORY,
            "test-token",
            transport=lambda method, url, headers, payload: (200, {}),
        )

        with patch.object(provider.__class__, "_default_transport"), patch(
            "ci_diagnosis._LOG_HTTP_OPENER.open",
            return_value=response,
        ):
            with self.assertRaisesRegex(
                CIDiagnosisError,
                "download limit",
            ):
                provider._download_job_log(101)

        self.assertEqual(MAX_LOG_DOWNLOAD_BYTES + 1, response.requested_size)

    def test_http_job_log_download_accepts_limit_sized_response(self):
        from ci_diagnosis import GitHubCIDiagnosisProvider, MAX_LOG_DOWNLOAD_BYTES

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_value, traceback):
                return False

            def read(self, size=-1):
                self.requested_size = size
                return b"x" * MAX_LOG_DOWNLOAD_BYTES

        response = Response()
        provider = GitHubCIDiagnosisProvider(
            REPOSITORY,
            "test-token",
            transport=lambda method, url, headers, payload: (200, {}),
        )

        with patch(
            "ci_diagnosis._LOG_HTTP_OPENER.open",
            return_value=response,
        ):
            result = provider._download_job_log(101)

        self.assertEqual(MAX_LOG_DOWNLOAD_BYTES, len(result.encode("utf-8")))
        self.assertEqual(MAX_LOG_DOWNLOAD_BYTES + 1, response.requested_size)

    def test_invalid_log_limit_fails_closed(self):
        with self.assertRaisesRegex(CIDiagnosisError, "Log limit"):
            _bounded_excerpt("log", limit=0)

    def test_latest_run_contract_is_provider_neutral(self):
        provider = FakeProvider()
        result = provider.latest_run(".github/workflows/validate.yml", "ai/integration")
        self.assertEqual(101, result.run_id)


if __name__ == "__main__":
    unittest.main()
