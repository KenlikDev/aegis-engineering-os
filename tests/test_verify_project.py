import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from verify_project import (  # noqa: E402
    _open_regular_file_no_follow,
    _read_regular_file_no_follow,
    sha256_file,
)


class VerifyProjectSecureReadTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "posix":
            self.skipTest("Verifier secure-read tests require POSIX no-follow support.")

    def test_reads_regular_file_without_following_final_symlink(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "regular.txt"
            regular.write_text("trusted\n", encoding="utf-8")
            link = root / "link.txt"
            link.symlink_to(regular)

            with self.assertRaises(OSError):
                _read_regular_file_no_follow(link)

    def test_rejects_symlinked_parent_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            external = root / "external"
            external.mkdir()
            (external / "state.json").write_text("{}\n", encoding="utf-8")

            redirected = root / "project"
            redirected.symlink_to(external, target_is_directory=True)

            with self.assertRaises(OSError):
                _read_regular_file_no_follow(redirected / "state.json")

    def test_sha256_file_reads_regular_file_through_secure_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "skill.md"
            payload = b"# Skill\n"
            path.write_bytes(payload)

            self.assertEqual(
                hashlib.sha256(payload).hexdigest(),
                sha256_file(path),
            )

    def test_sha256_file_rejects_symlinked_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            regular = root / "skill.md"
            regular.write_text("# Skill\n", encoding="utf-8")
            link = root / "linked-skill.md"
            link.symlink_to(regular)

            with self.assertRaises(OSError):
                sha256_file(link)

    def test_open_regular_file_uses_independent_file_descriptor(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "skill.md"
            path.write_text("# Skill\n", encoding="utf-8")
            file_fd = _open_regular_file_no_follow(path)
            try:
                self.assertGreaterEqual(file_fd, 0)
                self.assertEqual(b"# Skill\n", os.read(file_fd, 4096))
            finally:
                os.close(file_fd)


class VerifyProjectStateReadTests(unittest.TestCase):
    def test_expected_state_shape_uses_strict_json_reader(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state_path = root / ".aegis" / "aegis-version.json"
            state_path.parent.mkdir()
            payload = {
                "schema_version": 2,
                "aegis_version": "0.1.0-alpha.1",
                "source_repository": "KenlikDev/aegis-engineering-os",
                "source_commit": "a" * 40,
                "source_worktree_clean": True,
                "preset": "core",
                "integrations": [],
                "skills": ["example"],
                "skill_checksums": {"example": "b" * 64},
                "status": "active",
            }
            state_path.write_text(
                json.dumps(payload, sort_keys=True),
                encoding="utf-8",
            )

            parsed = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(2, parsed["schema_version"])
            self.assertEqual("active", parsed["status"])


if __name__ == "__main__":
    unittest.main()
