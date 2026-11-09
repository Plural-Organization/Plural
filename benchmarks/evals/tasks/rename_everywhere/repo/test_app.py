import unittest

from app.api import show
from app.jobs import nightly
from app.plugins import call
from app.store import fetch_user


class App(unittest.TestCase):
    def test_all(self):
        self.assertEqual(fetch_user(1), "ada")
        self.assertEqual(show(1), {"name": "ada"})
        self.assertEqual(nightly(), ["ada"])
        self.assertEqual(call("user", 1), "ada")
