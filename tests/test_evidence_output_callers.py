import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CALLERS = (
    ROOT / "tools" / "state_verification.py",
    ROOT / "tools" / "implementation_readiness.py",
    ROOT / "tools" / "version_verification.py",
    ROOT / "tools" / "integration_delivery.py",
    ROOT / "tools" / "integration_merge.py",
    ROOT / "tools" / "promotion_sync.py",
    ROOT / "tools" / "preflight_runtime.py",
    ROOT / "tools" / "testing.py",
)


def _is_resolve_call(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve"
    )


def _resolved_path_assignments(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        if not _is_resolve_call(node.value):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Name):
                names.add(target.id)
    return names


class EvidenceOutputCallerTests(unittest.TestCase):
    def test_specialized_evidence_writers_use_atomic_primitive(self) -> None:
        required = {
            "tools/aegis_orchestrator.py",
            "tools/evidence_bundle.py",
            "tools/quality_gates.py",
            "tools/testing.py",
            "tools/version_verification.py",
        }
        for relative_path in required:
            path = ROOT / relative_path
            source = path.read_text(encoding="utf-8")
            self.assertIn(
                "write_json_atomically(",
                source,
                relative_path,
            )

    def test_canonical_writer_never_receives_a_resolved_output_path(self) -> None:
        for path in CALLERS:
            tree = ast.parse(
                path.read_text(encoding="utf-8"),
                filename=str(path),
            )
            resolved_names = _resolved_path_assignments(tree)

            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (
                    isinstance(node.func, ast.Name)
                    and node.func.id == "write_evidence"
                ):
                    continue
                if len(node.args) < 2:
                    self.fail(
                        f"{path} calls write_evidence without an explicit output argument."
                    )

                output = node.args[1]
                self.assertFalse(
                    _is_resolve_call(output),
                    f"{path}:{node.lineno} resolves the canonical output before write_evidence().",
                )
                if isinstance(output, ast.Name):
                    self.assertNotIn(
                        output.id,
                        resolved_names,
                        f"{path}:{node.lineno} passes a variable already populated by Path.resolve().",
                    )


if __name__ == "__main__":
    unittest.main()
