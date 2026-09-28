import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class RuntimeToolInventoryTests(unittest.TestCase):
    def test_core_runtime_tools_exist(self):
        for relative_path in (
            "tools/preflight_runtime.py",
            "tools/openhands_execution.py",
            "tools/aegis_orchestrator.py",
            "tools/live_e2e_smoke_test.py",
        ):
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())

    def test_runtime_architecture_documents_exist(self):
        for relative_path in (
            "docs/architecture/runtime.md",
            "docs/architecture/openhands-execution.md",
            "docs/architecture/context-loading.md",
        ):
            with self.subTest(path=relative_path):
                self.assertTrue((ROOT / relative_path).is_file())


if __name__ == "__main__":
    unittest.main()
