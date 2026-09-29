import unittest


class GitHubHttpSecurityTests(unittest.TestCase):
    def test_exposes_mandatory_github_api_version_headers(self):
        from github_http_security import (
            GITHUB_API_VERSION,
            GITHUB_API_VERSION_HEADER,
            github_api_headers,
        )

        headers = github_api_headers()
        self.assertEqual("X-GitHub-Api-Version", GITHUB_API_VERSION_HEADER)
        self.assertEqual("2026-03-10", GITHUB_API_VERSION)
        self.assertEqual("2026-03-10", headers["X-GitHub-Api-Version"])
        self.assertEqual("application/vnd.github+json", headers["Accept"])

    def test_validates_exact_github_api_origin(self):
        from github_http_security import (
            GITHUB_API_ORIGIN,
            validate_github_api_base_url,
        )

        self.assertEqual(
            GITHUB_API_ORIGIN,
            validate_github_api_base_url("https://api.github.com"),
        )
        self.assertEqual(
            GITHUB_API_ORIGIN,
            validate_github_api_base_url("https://api.github.com/"),
        )

    def test_rejects_untrusted_github_api_destinations(self):
        from github_http_security import validate_github_api_base_url

        invalid_urls = (
            "https://api.github.com.attacker.example",
            "https://attacker.example",
            "https://api.github.com/api/v1",
            "https://user:password@api.github.com",
            "https://api.github.com:8443",
            " https://api.github.com",
            "https://api.github.com?redirect=1",
            "https://api.github.com#fragment",
        )

        for invalid_url in invalid_urls:
            with self.subTest(api_base_url=invalid_url):
                with self.assertRaises(ValueError):
                    validate_github_api_base_url(invalid_url)

    def test_github_adapters_use_bounded_transport(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        adapters = (
            "tools/delivery.py",
            "tools/integration_merge.py",
            "tools/promotion_snapshot.py",
            "tools/promotion_readiness.py",
            "tools/promotion_sync.py",
            "tools/work_item_lifecycle.py",
            "tools/release_readiness.py",
            "tools/ci_diagnosis.py",
        )

        for relative_path in adapters:
            with self.subTest(adapter=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8")
                self.assertIn("read_bounded_response(", source)
                self.assertIn("validate_github_api_base_url(", source)
                self.assertNotIn("response.read()", source)
                self.assertNotIn("exc.read()", source)

    def test_github_adapters_use_shared_baseline_headers(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        adapters = (
            "tools/delivery.py",
            "tools/integration_merge.py",
            "tools/promotion_snapshot.py",
            "tools/promotion_readiness.py",
            "tools/promotion_sync.py",
            "tools/work_item_lifecycle.py",
            "tools/release_readiness.py",
            "tools/ci_diagnosis.py",
        )

        for relative_path in adapters:
            with self.subTest(adapter=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8")
                self.assertIn("github_api_headers()", source)
                self.assertNotIn('"X-GitHub-Api-Version":', source)
                self.assertNotIn('GITHUB_API_VERSION =', source)

    def test_parses_strict_github_json(self):
        from github_http_security import parse_github_json

        self.assertEqual(
            {"items": [1, 2, 3]},
            parse_github_json(b'{"items":[1,2,3]}'),
        )
        self.assertEqual(
            [1, 2, 3],
            parse_github_json(b"[1,2,3]"),
        )

        with self.assertRaisesRegex(ValueError, "Duplicate JSON key"):
            parse_github_json(b'{"status":"ok","status":"verified"}')

        with self.assertRaisesRegex(ValueError, "unsupported constant"):
            parse_github_json(b'{"value":NaN}')

    def test_github_adapters_use_shared_strict_json_parser(self):
        from pathlib import Path

        root = Path(__file__).resolve().parents[1]
        adapters = (
            "tools/ci_diagnosis.py",
            "tools/delivery.py",
            "tools/integration_merge.py",
            "tools/promotion_readiness.py",
            "tools/promotion_snapshot.py",
            "tools/promotion_sync.py",
            "tools/release_readiness.py",
            "tools/work_item_lifecycle.py",
        )

        for relative_path in adapters:
            with self.subTest(adapter=relative_path):
                source = (root / relative_path).read_text(encoding="utf-8")
                self.assertIn("parse_github_json(", source)
                self.assertNotIn("json.loads(", source)

    def test_bounds_response_reads(self):
        from github_http_security import MAX_GITHUB_JSON_BYTES, read_bounded_response

        class Response:
            def __init__(self, payload):
                self.payload = payload
                self.requested_size = None

            def read(self, size=-1):
                self.requested_size = size
                return self.payload

        response = Response(b"x" * (MAX_GITHUB_JSON_BYTES + 1))
        with self.assertRaisesRegex(ValueError, "download limit"):
            read_bounded_response(response)
        self.assertEqual(MAX_GITHUB_JSON_BYTES + 1, response.requested_size)

    def test_accepts_limit_sized_response(self):
        from github_http_security import MAX_GITHUB_JSON_BYTES, read_bounded_response

        class Response:
            def read(self, size=-1):
                self.requested_size = size
                return b"x" * MAX_GITHUB_JSON_BYTES

        response = Response()
        payload = read_bounded_response(response)
        self.assertEqual(MAX_GITHUB_JSON_BYTES, len(payload))
        self.assertEqual(MAX_GITHUB_JSON_BYTES + 1, response.requested_size)


if __name__ == "__main__":
    unittest.main()
