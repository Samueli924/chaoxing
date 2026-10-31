import unittest

from api.cookies import parse_cookie_string


class TestParseCookieString(unittest.TestCase):
    def test_parses_pairs(self):
        self.assertEqual(
            parse_cookie_string("_uid=419769884; UID=419769884; fid=1234"),
            {"_uid": "419769884", "UID": "419769884", "fid": "1234"},
        )

    def test_keeps_value_with_equals_sign(self):
        self.assertEqual(parse_cookie_string("token=abc=def"), {"token": "abc=def"})

    def test_trims_whitespace(self):
        self.assertEqual(parse_cookie_string("  a = 1 ;  b=2  "), {"a": "1", "b": "2"})

    def test_empty_input_returns_empty_dict(self):
        self.assertEqual(parse_cookie_string(""), {})
        self.assertEqual(parse_cookie_string(None), {})

    def test_skips_fragments_without_value(self):
        self.assertEqual(parse_cookie_string("a=1; broken; =nokey; b=2"), {"a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()
