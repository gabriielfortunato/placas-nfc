import unittest

from app import SLUG_RE, valid_target


class ValidationTests(unittest.TestCase):
    def test_accepts_http_and_https_urls(self):
        self.assertTrue(valid_target("https://example.com/reviews"))
        self.assertTrue(valid_target("http://example.com/path?q=1"))

    def test_rejects_non_http_schemes_and_malformed_urls(self):
        self.assertFalse(valid_target("javascript:alert(1)"))
        self.assertFalse(valid_target("ftp://example.com/file"))
        self.assertFalse(valid_target("https://"))
        self.assertFalse(valid_target("https://example.com:99999"))
        self.assertFalse(valid_target("https://example.com/a b"))

    def test_slug_format(self):
        self.assertRegex("placa-123", SLUG_RE)
        self.assertRegex("loja", SLUG_RE)
        self.assertNotRegex("Loja", SLUG_RE)
        self.assertNotRegex("-loja", SLUG_RE)
        self.assertNotRegex("loja--centro", SLUG_RE)


if __name__ == "__main__":
    unittest.main()
