"""Tests for the built-in checks of privacy_scan.py.

Sample values are assembled at runtime so that this file itself never contains anything the scan would flag.
Run: python -m unittest discover -s tools -p "test_*.py"
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from privacy_scan import BUILTIN  # noqa: E402

DOT = "."


def hits(name, text):
    return [m.group(0) for m in BUILTIN[name].finditer(text)]


class EntityIdCheck(unittest.TestCase):
    def test_flags_entity_ids_in_config_and_templates(self):
        samples = [
            "action: notify" + DOT + "mobile_app_phone",
            "entity_id: binary_sensor" + DOT + "front_door",
            "{{ is_state('person" + DOT + "someone', 'home') }}",
            "- automation" + DOT + "morning_lights",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(len(hits("HA entity id", text)), 1)

    def test_ignores_function_calls(self):
        samples = [
            "automation" + DOT + "register_action(",
            "await binary_sensor" + DOT + "new_binary_sensor(config)",
            "automation" + DOT + "validate_automation (schema)",
        ]
        for text in samples:
            with self.subTest(text=text):
                self.assertEqual(hits("HA entity id", text), [])


class AddressChecks(unittest.TestCase):
    def test_private_ipv4(self):
        self.assertEqual(len(hits("private IPv4", "host " + DOT.join(["192", "168", "1", "5"]))), 1)
        self.assertEqual(hits("private IPv4", "public " + DOT.join(["8", "8", "8", "8"])), [])

    def test_mac_address(self):
        self.assertEqual(len(hits("MAC address", ":".join(["aa", "bb", "cc", "dd", "ee", "ff"]))), 1)

    def test_email(self):
        self.assertEqual(len(hits("e-mail address", "someone" + "@" + "example" + DOT + "org")), 1)


if __name__ == "__main__":
    unittest.main()
