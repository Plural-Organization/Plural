import unittest

from durations import parse, render


class Durations(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(parse("1h30m"), 5400)
        self.assertEqual(parse("90s"), 90)

    def test_refuses_garbage(self):
        with self.assertRaises(ValueError):
            parse("soon")

    def test_render(self):
        self.assertEqual(render(5400), "1h30m")
        self.assertEqual(render(0), "0s")
        self.assertEqual(render(3661), "1h1m1s")
