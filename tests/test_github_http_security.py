import unittest


class GitHubHttpSecurityTests(unittest.TestCase):
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
