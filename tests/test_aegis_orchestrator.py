import json
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from version_verification import record_version_evidence  # noqa: E402
from work_item_lifecycle import (  # noqa: E402
    InMemoryWorkItemProvider,
    LifecycleState,
    MutationEvidence,
    WorkItem,
)


@dataclass(frozen=True, slots=True)
class FakeRequest:
    server_url: str
    workspace: str
    task: str
    agent_settings: dict
    confirmation_policy: dict
    expected_agent_server_version: str
    max_iterations: int
    timeout_seconds: float
    poll_interval_seconds: float
    workspace_root: str
    session_api_key: str | None


_module_backups = {
    name: sys.modules.get(name)
    for name in (
        "openhands_execution",
        "preflight_runtime",
        "render_openhands_profile",
    )
}

fake_openhands = types.ModuleType("openhands_execution")
fake_openhands.OpenHandsExecutionClient = object
fake_openhands.OpenHandsExecutionError = RuntimeError
fake_openhands.OpenHandsExecutionRequest = FakeRequest
sys.modules["openhands_execution"] = fake_openhands

fake_preflight = types.ModuleType("preflight_runtime")
fake_preflight.RuntimePreflightError = RuntimeError
fake_preflight.preflight = lambda *args, **kwargs: {}
sys.modules["preflight_runtime"] = fake_preflight

fake_render = types.ModuleType("render_openhands_profile")
fake_render.render_profile = lambda *args, **kwargs: {
    "provider": "ollama",
    "surface": "local",
    "integration": "openhands_llm_ollama",
    "connection_mode": "local",
    "openhands_agent_kind": "llm",
    "llm_model": "openai/gemma4:31b",
    "llm_base_url": "http://host.docker.internal:11434/v1",
    "api_key_placeholder": "local-llm",
}
sys.modules["render_openhands_profile"] = fake_render

try:
    import aegis_orchestrator  # noqa: E402
finally:
    for name, module in _module_backups.items():
        if module is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


class UnverifiedMutationWorkItemProvider(InMemoryWorkItemProvider):
    def __init__(
        self,
        items,
        unverified_operation,
        unverified_state=None,
    ):
        super().__init__(items)
        self.unverified_operation = unverified_operation
        self.unverified_state = unverified_state

    def _should_fail(self, work_item_id):
        if self.unverified_state is None:
            return True
        return self.get(work_item_id).state == self.unverified_state

    @staticmethod
    def _unverified(evidence):
        return MutationEvidence(
            provider=evidence.provider,
            operation=evidence.operation,
            work_item_id=evidence.work_item_id,
            state_before=evidence.state_before,
            state_after=evidence.state_after,
            verified=False,
            reference=evidence.reference,
            identifier=evidence.identifier,
        )

    def transition(self, work_item_id, *args, **kwargs):
        should_fail = (
            self.unverified_operation == "transition"
            and self._should_fail(work_item_id)
        )
        evidence = super().transition(work_item_id, *args, **kwargs)
        return self._unverified(evidence) if should_fail else evidence

    def attach_traceability(self, work_item_id, *args, **kwargs):
        should_fail = (
            self.unverified_operation == "traceability"
            and self._should_fail(work_item_id)
        )
        evidence = super().attach_traceability(work_item_id, *args, **kwargs)
        return self._unverified(evidence) if should_fail else evidence

    def comment(self, work_item_id, *args, **kwargs):
        should_fail = (
            self.unverified_operation == "comment"
            and self._should_fail(work_item_id)
        )
        evidence = super().comment(work_item_id, *args, **kwargs)
        return self._unverified(evidence) if should_fail else evidence


class AegisOrchestratorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self._git("init", "-b", "ai/integration")
        self._git("config", "user.email", "aegis-test@example.invalid")
        self._git("config", "user.name", "Aegis Test")
        (self.project / "README.md").write_text("test\n", encoding="utf-8")
        self._write_readiness_document("51")
        self._git(
            "add",
            "README.md",
            "work-item.md",
            "version-claims.json",
            "version-source.txt",
            ".aegis/version-evidence.json",
        )
        self._git("commit", "-m", "test: initialize repository")

    def _write_readiness_document(self, work_item_id: str) -> None:
        document = f"""# Work Item

## Identity

Provider: memory
Work item ID: {work_item_id}
Title: Managed execution readiness test

## Intent

The managed execution test must verify readiness before execution.

## Scope

### In scope

- managed readiness verification

### Out of scope

- unrelated product behavior

## Acceptance criteria

- [ ] Readiness is checked before execution.

## Dependencies

- Python runtime

## Roles

Primary role: software engineer

## Technical notes

Affected component: test fixture

## Risks

- Missing readiness evidence must block execution.

## Verification plan

- Run the Aegis policy tests.

## Delivery links

Branch:
Pull request:
Documentation:
ADR:

## Status log

Test fixture.

## Definition of done

- [ ] Acceptance criteria satisfied
"""
        (self.project / "work-item.md").write_text(document, encoding="utf-8")
        claims = self.project / "version-claims.json"
        claims.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "claims": [
                        {
                            "component": "python",
                            "version": "3.13",
                            "scope": "language",
                            "source": "version-source.txt",
                        }
                    ],
                    "external_verification_pending": False,
                }
            ),
            encoding="utf-8",
        )
        (self.project / "version-source.txt").write_text(
            "Python 3.13 toolchain evidence.\n",
            encoding="utf-8",
        )
        evidence = self.project / ".aegis" / "version-evidence.json"
        evidence.parent.mkdir()
        record_version_evidence(self.project, claims, evidence)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.project), *args],
            check=check,
            text=True,
            capture_output=True,
        )

    def _config(
        self,
        task: str = "Implement the requested change.",
        *,
        work_item_id: str = "51",
        work_item_provider: InMemoryWorkItemProvider | None = None,
    ) -> aegis_orchestrator.OrchestratorConfig:
        return aegis_orchestrator.OrchestratorConfig(
            project_path=self.project,
            work_item_id=work_item_id,
            work_item_kind="feature",
            work_item_document=self.project / "work-item.md",
            version_evidence_ref=self.project / ".aegis" / "version-evidence.json",
            architecture_required=False,
            work_item_provider=work_item_provider,
            task=task,
            agent_server_url="http://127.0.0.1:8000",
            container_workspace="/projects/aegis-target",
            profile_config=self.project / "profiles.json",
            expected_model="gemma4:31b",
            expected_ollama_version="0.34.3",
            expected_openhands_version="1.49.5",
        )

    def _preflight(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return {
            "ollama_version": "0.34.3",
            "model": "gemma4:31b",
            "openhands_agent_server": {
                "version": "1.49.5",
                "sdk_version": "1.49.5",
                "tools_version": "1.49.5",
                "workspace_version": "1.49.5",
                "conversation_runtime": "local",
            },
        }

    def _ready_provider(self) -> InMemoryWorkItemProvider:
        return InMemoryWorkItemProvider(
            {
                "51": WorkItem(
                    id="51",
                    title="managed execution",
                    state=LifecycleState.READY,
                    provider="memory",
                )
            }
        )

    def test_ready_to_in_progress_fails_closed_on_unverified_traceability(self) -> None:
        provider = UnverifiedMutationWorkItemProvider(
            {
                "51": WorkItem(
                    id="51",
                    title="managed execution",
                    state=LifecycleState.READY,
                    provider="memory",
                )
            },
            "traceability",
        )
        executed = {"value": False}

        def execute(request):
            executed["value"] = True
            raise AssertionError("OpenHands must not start after unverified traceability.")

        with self.assertRaises(aegis_orchestrator.WorkItemLifecycleError):
            aegis_orchestrator.orchestrate(
                self._config(work_item_provider=provider),
                preflight_fn=self._preflight,
                execute_fn=execute,
            )

        self.assertFalse(executed["value"])
        self.assertEqual(LifecycleState.READY, provider.get("51").state)

    def test_ready_to_in_progress_fails_closed_on_unverified_transition(self) -> None:
        provider = UnverifiedMutationWorkItemProvider(
            {
                "51": WorkItem(
                    id="51",
                    title="managed execution",
                    state=LifecycleState.READY,
                    provider="memory",
                )
            },
            "transition",
        )
        executed = {"value": False}

        def execute(request):
            executed["value"] = True
            raise AssertionError("OpenHands must not start after unverified transition.")

        with self.assertRaises(aegis_orchestrator.WorkItemLifecycleError):
            aegis_orchestrator.orchestrate(
                self._config(work_item_provider=provider),
                preflight_fn=self._preflight,
                execute_fn=execute,
            )

        self.assertFalse(executed["value"])
        self.assertEqual(LifecycleState.IN_PROGRESS, provider.get("51").state)

    def test_success_to_verification_fails_closed_on_unverified_traceability(self) -> None:
        provider = UnverifiedMutationWorkItemProvider(
            {
                "51": WorkItem(
                    id="51",
                    title="managed execution",
                    state=LifecycleState.READY,
                    provider="memory",
                )
            },
            "traceability",
            unverified_state=LifecycleState.IN_PROGRESS,
        )
        project = self.project

        class SuccessClient:
            def execute(self, request):
                (project / "result.txt").write_text("done\n", encoding="utf-8")
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = SuccessClient
        try:
            with self.assertRaises(aegis_orchestrator.WorkItemLifecycleError):
                aegis_orchestrator.orchestrate(
                    self._config(work_item_provider=provider),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertEqual(LifecycleState.IN_PROGRESS, provider.get("51").state)

    def test_success_to_verification_fails_closed_on_unverified_transition(self) -> None:
        provider = UnverifiedMutationWorkItemProvider(
            {
                "51": WorkItem(
                    id="51",
                    title="managed execution",
                    state=LifecycleState.READY,
                    provider="memory",
                )
            },
            "transition",
            unverified_state=LifecycleState.IN_PROGRESS,
        )
        project = self.project

        class SuccessClient:
            def execute(self, request):
                (project / "result.txt").write_text("done\n", encoding="utf-8")
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = SuccessClient
        try:
            with self.assertRaises(aegis_orchestrator.WorkItemLifecycleError):
                aegis_orchestrator.orchestrate(
                    self._config(work_item_provider=provider),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertEqual(LifecycleState.IN_PROGRESS, provider.get("51").state)

    def test_work_item_must_be_ready_before_execution(self) -> None:
        provider = InMemoryWorkItemProvider(
            {
                "51": WorkItem(
                    id="51",
                    title="managed execution",
                    state=LifecycleState.PLANNED,
                    provider="memory",
                )
            }
        )
        with self.assertRaises(aegis_orchestrator.AegisOrchestratorError):
            aegis_orchestrator.orchestrate(
                self._config(
                    work_item_id="51",
                    work_item_provider=provider,
                ),
                preflight_fn=self._preflight,
            )
        branches = self._git("branch", "--format=%(refname:short)").stdout.splitlines()
        self.assertNotIn("ai/feature/51-execution", branches)

    def test_success_synchronizes_work_item_to_verification(self) -> None:
        provider = self._ready_provider()
        project = self.project

        class SuccessClient:
            def execute(self, request):
                (project / "result.txt").write_text(
                    "done\n", encoding="utf-8"
                )
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = SuccessClient
        try:
            evidence = aegis_orchestrator.orchestrate(
                self._config(
                    "Implement result.txt.",
                    work_item_id="51",
                    work_item_provider=provider,
                ),
                preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        item = provider.get("51")
        self.assertEqual(LifecycleState.VERIFICATION, item.state)
        self.assertEqual("verification", evidence["work_item"]["state_after_execution"])
        comments = provider.comments["51"]
        self.assertEqual(2, len(comments))
        self.assertIn("ai/feature/51-execution", comments[0])
        self.assertIn("12345178-1234-5178-1234-517812345178", comments[1])
        self.assertTrue(evidence["work_item"]["verified"])

    def test_execution_failure_blocks_work_item_without_leaking_error(self) -> None:
        provider = self._ready_provider()

        class FailingClient:
            def execute(self, request):
                raise RuntimeError("super-secret-provider-response")

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = FailingClient
        try:
            with self.assertRaises(RuntimeError):
                aegis_orchestrator.orchestrate(
                    self._config(
                        work_item_id="51",
                        work_item_provider=provider,
                    ),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertEqual(LifecycleState.BLOCKED, provider.get("51").state)
        failure_comment = provider.comments["51"][-1]
        self.assertIn("RuntimeError", failure_comment)
        self.assertNotIn("super-secret-provider-response", failure_comment)

    def test_post_execution_git_integrity_failure_blocks_work_item(self) -> None:
        provider = self._ready_provider()
        project = self.project

        class BranchChangingClient:
            def execute(self, request):
                subprocess.run(
                    ["git", "-C", str(project), "switch", "-c", "ai/fix/other"],
                    check=True,
                    text=True,
                    capture_output=True,
                )
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = BranchChangingClient
        try:
            with self.assertRaises(aegis_orchestrator.AegisOrchestratorError):
                aegis_orchestrator.orchestrate(
                    self._config(
                        work_item_id="51",
                        work_item_provider=provider,
                    ),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertEqual(LifecycleState.BLOCKED, provider.get("51").state)
        self.assertIn("AegisOrchestratorError", provider.comments["51"][-1])

    def test_build_task_branch_name_preserves_work_item_identity(self) -> None:
        self.assertEqual(
            "ai/feature/51-execution",
            aegis_orchestrator.build_task_branch_name("#51"),
        )

    def test_task_prompt_keeps_git_lifecycle_under_aegis_control(self) -> None:
        prompt = aegis_orchestrator.build_execution_task("Edit the API.", "51")
        self.assertIn("Work item: 51", prompt)
        self.assertIn("Do not commit changes", prompt)
        self.assertIn("Do not commit changes, create commits, amend commits, push", prompt)
        self.assertIn("--- BEGIN USER TASK ---", prompt)
        self.assertIn("Edit the API.", prompt)

    def test_work_item_kind_must_match_branch_kind(self):
        config = self._config()
        mismatched = replace(
            config,
            work_item_kind="refactoring",
            branch_kind="feature",
        )
        with self.assertRaisesRegex(
            aegis_orchestrator.AegisOrchestratorError,
            "requires branch kind",
        ):
            aegis_orchestrator.orchestrate(
                mismatched,
                preflight_fn=self._preflight,
            )
        branches = self._git("branch", "--format=%(refname:short)").stdout.splitlines()
        self.assertNotIn("ai/feature/51-execution", branches)

    def test_readiness_failure_prevents_task_branch_creation(self):
        config = self._config()
        mismatched = replace(
            config,
            version_evidence_ref=self.project / "missing-version-evidence.txt",
        )

        with self.assertRaisesRegex(
            aegis_orchestrator.AegisOrchestratorError,
            "Implementation readiness",
        ):
            aegis_orchestrator.orchestrate(
                mismatched,
                preflight_fn=self._preflight,
            )

        branches = self._git("branch", "--format=%(refname:short)").stdout.splitlines()
        self.assertNotIn("ai/feature/51-execution", branches)

    def test_preflight_failure_does_not_create_task_branch(self) -> None:
        def failed_preflight(*args, **kwargs):  # noqa: ANN002, ANN003
            raise RuntimeError("preflight failed")

        with self.assertRaises(RuntimeError):
            aegis_orchestrator.orchestrate(
                self._config(),
                preflight_fn=failed_preflight,
            )
        branches = self._git("branch", "--format=%(refname:short)").stdout.splitlines()
        self.assertNotIn("ai/feature/51-execution", branches)

    def test_protected_branch_is_rejected(self) -> None:
        self._git("switch", "-c", "main")
        with self.assertRaises(aegis_orchestrator.AegisOrchestratorError):
            aegis_orchestrator.inspect_git_state(self.project)

    def test_dirty_worktree_is_rejected_before_execution(self) -> None:
        (self.project / "dirty.txt").write_text("dirty\n", encoding="utf-8")
        with self.assertRaises(aegis_orchestrator.AegisOrchestratorError):
            aegis_orchestrator.orchestrate(
                self._config(),
                preflight_fn=self._preflight,
            )
        self.assertEqual(
            "ai/integration",
            self._git("symbolic-ref", "--short", "HEAD").stdout.strip(),
        )

    def test_invalid_container_workspace_is_rejected(self) -> None:
        with self.assertRaises(aegis_orchestrator.AegisOrchestratorError):
            aegis_orchestrator.validate_container_workspace("/projects/../outside")

    def test_success_creates_task_branch_and_leaves_changes_uncommitted(self) -> None:
        captured = {}

        class FakeClient:
            def execute(self, request):
                captured["request"] = request
                (self_project_ref[0] / "src.txt").write_text(
                    "changed\n", encoding="utf-8"
                )
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        self_project_ref = [self.project]
        fake_client_instance = FakeClient()
        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = lambda: fake_client_instance
        try:
            evidence = aegis_orchestrator.orchestrate(
                self._config("Add src.txt."),
                preflight_fn=self._preflight,
            )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertEqual("verified", evidence["status"])
        self.assertEqual("ai/feature/51-execution", evidence["branch"]["task"])
        self.assertTrue(evidence["branch"]["head_unchanged"])
        self.assertTrue(evidence["git"]["working_tree_changed"])
        self.assertEqual("finished", evidence["execution"]["outcome"])
        self.assertEqual(
            "ConfirmRisky",
            captured["request"].confirmation_policy["kind"],
        )
        self.assertIn(
            "Do not commit changes, create commits, amend commits, push",
            captured["request"].task,
        )

    def test_finished_execution_without_changes_is_rejected(self) -> None:
        class NoChangeClient:
            def execute(self, request):
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = NoChangeClient
        try:
            with self.assertRaises(aegis_orchestrator.AegisOrchestratorError) as context:
                aegis_orchestrator.orchestrate(
                    self._config(),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertIn(
            "produced no inspectable working-tree changes",
            str(context.exception),
        )

    def test_agent_side_commit_is_detected(self) -> None:
        project = self.project

        class CommitClient:
            def execute(self, request):
                target = project / "committed.txt"
                target.write_text("bad\n", encoding="utf-8")
                self._git("add", "committed.txt")
                self._git("commit", "-m", "bad: agent-side commit")
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

            def _git(self, *args: str):
                return subprocess.run(
                    ["git", "-C", str(project), *args],
                    check=True,
                    text=True,
                    capture_output=True,
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = CommitClient
        try:
            with self.assertRaises(aegis_orchestrator.AegisOrchestratorError) as context:
                aegis_orchestrator.orchestrate(
                    self._config(),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertIn("changed Git HEAD", str(context.exception))

    def test_openhands_branch_switch_is_detected(self) -> None:
        self._git("branch", "ai/fix/other")

        project = self.project

        class BranchChangingClient:
            def execute(self, request):
                subprocess.run(
                    ["git", "-C", str(project), "switch", "ai/fix/other"],
                    check=True,
                    text=True,
                    capture_output=True,
                )
                (project / "changed.txt").write_text("bad\n", encoding="utf-8")
                return types.SimpleNamespace(
                    conversation_id="12345178-1234-5178-1234-517812345178",
                    execution_status="finished",
                    outcome="finished",
                    events=(),
                )

        original = aegis_orchestrator.OpenHandsExecutionClient
        aegis_orchestrator.OpenHandsExecutionClient = BranchChangingClient
        try:
            with self.assertRaises(aegis_orchestrator.AegisOrchestratorError) as context:
                aegis_orchestrator.orchestrate(
                    self._config(),
                    preflight_fn=self._preflight,
                )
        finally:
            aegis_orchestrator.OpenHandsExecutionClient = original

        self.assertIn("changed the Git branch", str(context.exception))


if __name__ == "__main__":
    unittest.main()
