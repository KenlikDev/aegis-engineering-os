import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from live_e2e_smoke_test import (  # noqa: E402
    EXPECTED_FILE_CONTENT,
    EXPECTED_FILE_NAME,
    LiveE2EConfig,
    LiveE2EError,
    _cleanup_workspace,
    _container_workspace,
    _event_summary,
    _task_text,
    _validate_loopback_url,
    _verify_workspace_artifact,
    run_live_smoke_test,
)


class LiveE2ESmokeTest(unittest.TestCase):
    def test_loopback_url_validation(self) -> None:
        self.assertEqual(
            "http://127.0.0.1:8000",
            _validate_loopback_url("http://127.0.0.1:8000/"),
        )
        with self.assertRaises(LiveE2EError):
            _validate_loopback_url("http://192.0.2.10:8000")

    def test_container_workspace_is_mapped_to_direct_child(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            host_root = Path(root)
            workspace = host_root / "case-a"
            workspace.mkdir()
            self.assertEqual(
                "/projects/case-a",
                _container_workspace(workspace, host_root),
            )

            nested = workspace / "nested"
            nested.mkdir()
            with self.assertRaises(LiveE2EError):
                _container_workspace(nested, host_root)

    def test_task_text_is_deterministic(self) -> None:
        text = _task_text()
        self.assertIn(EXPECTED_FILE_NAME, text)
        self.assertIn(EXPECTED_FILE_CONTENT.rstrip(), text)

    def test_workspace_artifact_verification(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            workspace = Path(root)
            artifact = workspace / EXPECTED_FILE_NAME
            artifact.write_text(
                EXPECTED_FILE_CONTENT,
                encoding="utf-8",
            )
            evidence = _verify_workspace_artifact(workspace)
            self.assertTrue(evidence["content_verified"])

            (workspace / "unexpected.txt").write_text(
                "bad",
                encoding="utf-8",
            )
            with self.assertRaises(LiveE2EError):
                _verify_workspace_artifact(workspace)

    def test_cleanup_removes_only_workspace_child(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            host_root = Path(root)
            workspace = host_root / ".aegis-live-e2e-test"
            workspace.mkdir()
            (
                workspace / EXPECTED_FILE_NAME
            ).write_text(
                EXPECTED_FILE_CONTENT,
                encoding="utf-8",
            )
            result = _cleanup_workspace(workspace, host_root)
            self.assertEqual("removed", result["status"])
            self.assertFalse(workspace.exists())

    def test_event_summary_contains_types_and_count(self) -> None:
        result = _event_summary(
            (
                {"id": "1", "type": "AgentStarted"},
                {"id": "2", "type": "AgentStarted"},
                {"id": "3", "type": "AgentFinished"},
            )
        )
        self.assertEqual(3, result["count"])
        self.assertEqual(
            {"AgentStarted": 2, "AgentFinished": 1},
            result["type_counts"],
        )
        self.assertEqual("1", result["first_id"])
        self.assertEqual("3", result["last_id"])

    def test_full_flow_verifies_and_cleans_isolated_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            host_root = Path(root)
            captured = {}

            def fake_preflight(*args, **kwargs):  # noqa: ANN002, ANN003
                return {
                    "status": "verified",
                    "provider": "ollama",
                    "surface": "local",
                    "connection_mode": "local",
                    "model": "gemma4:31b",
                    "ollama_version": "0.34.3",
                    "openhands_agent_server": {
                        "status": "verified",
                        "version": "1.49.5",
                        "sdk_version": "1.49.5",
                        "tools_version": "1.49.5",
                        "workspace_version": "1.49.5",
                        "conversation_runtime": "local",
                    },
                }

            def fake_render(*args, **kwargs):  # noqa: ANN002, ANN003
                return (
                    {
                        "kind": "Agent",
                        "llm": {
                            "model": "openai/gemma4:31b",
                            "base_url": (
                                "http://host.docker.internal:11434/v1"
                            ),
                            "api_key": "local-llm",
                        },
                    },
                    {
                        "provider": "ollama",
                        "surface": "local",
                        "connection_mode": "local",
                        "integration": "openhands_llm_ollama",
                        "openhands_agent_kind": "llm",
                        "llm_model": "openai/gemma4:31b",
                        "llm_base_url": (
                            "http://host.docker.internal:11434/v1"
                        ),
                        "api_key_placeholder": "local-llm",
                    },
                )

            def fake_inspect(name):  # noqa: ANN001
                self.assertEqual("openhands", name)
                return "ghcr.io/openhands/agent-canvas:1.23.0"

            def fake_execute(request):  # noqa: ANN001
                captured["request"] = request
                relative = request.workspace.removeprefix("/projects/")
                workspace = host_root / relative
                (
                    workspace / EXPECTED_FILE_NAME
                ).write_text(
                    EXPECTED_FILE_CONTENT,
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    conversation_id=(
                        "12345678-1234-5678-1234-567812345678"
                    ),
                    execution_status="finished",
                    outcome="finished",
                    events=(
                        {"id": "1", "type": "AgentStarted"},
                        {"id": "2", "type": "AgentFinished"},
                    ),
                )

            config = LiveE2EConfig(
                profile_config=ROOT / "profiles.json",
                profile_name="development-local",
                agent_server_url="http://127.0.0.1:8000",
                host_workspace_root=host_root,
                openhands_container="openhands",
            )
            evidence = run_live_smoke_test(
                config,
                preflight_fn=fake_preflight,
                execute_fn=fake_execute,
                inspect_image_fn=fake_inspect,
                render_agent_fn=fake_render,
            )

            self.assertEqual("verified", evidence["status"])
            self.assertEqual(
                "finished",
                evidence["execution"]["outcome"],
            )
            self.assertEqual(
                2,
                evidence["execution"]["events"]["count"],
            )
            self.assertIn(
                "/projects/",
                captured["request"].workspace,
            )
            self.assertEqual(
                "NeverConfirm",
                captured["request"].confirmation_policy["kind"],
            )
            self.assertEqual(
                "10",
                str(captured["request"].max_iterations),
            )
            self.assertEqual(
                "removed",
                evidence["workspace"]["cleanup"]["status"],
            )
            self.assertEqual([], list(host_root.iterdir()))

    def test_failed_execution_still_cleans_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            host_root = Path(root)

            def fake_preflight(*args, **kwargs):  # noqa: ANN002, ANN003
                return {
                    "ollama_version": "0.34.3",
                    "openhands_agent_server": {
                        "version": "1.49.5",
                        "sdk_version": "1.49.5",
                        "tools_version": "1.49.5",
                        "workspace_version": "1.49.5",
                        "conversation_runtime": "local",
                    },
                }

            def fake_render(*args, **kwargs):  # noqa: ANN002, ANN003
                return (
                    {
                        "kind": "Agent",
                        "llm": {
                            "model": "openai/gemma4:31b",
                            "base_url": "http://host.docker.internal:11434/v1",
                            "api_key": "local-llm",
                        },
                    },
                    {
                        "provider": "ollama",
                        "surface": "local",
                        "connection_mode": "local",
                        "integration": "openhands_llm_ollama",
                        "openhands_agent_kind": "llm",
                        "llm_model": "openai/gemma4:31b",
                        "llm_base_url": (
                            "http://host.docker.internal:11434/v1"
                        ),
                        "api_key_placeholder": "local-llm",
                    },
                )

            def fake_inspect(name):  # noqa: ANN001
                return "ghcr.io/openhands/agent-canvas:1.23.0"

            def fake_execute(request):  # noqa: ANN001
                relative = request.workspace.removeprefix("/projects/")
                (
                    host_root / relative / EXPECTED_FILE_NAME
                ).write_text(
                    EXPECTED_FILE_CONTENT,
                    encoding="utf-8",
                )
                return SimpleNamespace(
                    conversation_id=(
                        "12345678-1234-5678-1234-567812345678"
                    ),
                    execution_status="error",
                    outcome="error",
                    events=(),
                )

            config = LiveE2EConfig(
                profile_config=ROOT / "profiles.json",
                profile_name="development-local",
                agent_server_url="http://127.0.0.1:8000",
                host_workspace_root=host_root,
                openhands_container="openhands",
            )
            with self.assertRaises(LiveE2EError):
                run_live_smoke_test(
                    config,
                    preflight_fn=fake_preflight,
                    execute_fn=fake_execute,
                    inspect_image_fn=fake_inspect,
                    render_agent_fn=fake_render,
                )
            self.assertEqual([], list(host_root.iterdir()))


if __name__ == "__main__":
    unittest.main()
