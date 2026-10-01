"""Who is speaking: the rule cases of roomkey's self-test (identity_cases.py) plus noise, prompt echo and speech checks."""
import unittest

import _path  # noqa: F401
from aikos_transcriber.identity import by_rules, classify, clean, is_noise, prompt_echo
from identity_cases import CASES, TYPE_CASES


class Rules(unittest.TestCase):
    def test_speaker_and_message(self):
        for text, speaker, message in CASES:
            side = "room" if text.startswith("room:") else "door"
            text = text.removeprefix("room:")
            with self.subTest(side=side, text=text):
                got = by_rules(text, known_names=("Jonas", "Anna"), side=side)
                self.assertEqual((got.speaker, got.message), (speaker, message))

    def test_visitor_type_and_urgent(self):
        for text, side, vtype, urgent in TYPE_CASES:
            with self.subTest(side=side, text=text):
                got = classify(by_rules(text, side=side), clean(text), side)
                self.assertEqual((got.vtype, got.urgent), (vtype, urgent))


class Text(unittest.TestCase):
    def test_noise(self):
        for noise in ["♪♪", "¶¶", "Untertitel im Auftrag des ZDF, 2020", " ", "Vielen Dank fürs Zuschauen!", "BELLS CHIMING", "Musik",
                      "[Musik]", "(Glocken läuten)", "*Klingeln*"]:
            with self.subTest(noise=noise):
                self.assertTrue(is_noise(noise))

    def test_speech_is_not_noise(self):
        for speech in ["Hallo? [Musik] Ist da jemand?", "DHL, Paket!", "Polizei! Vielen Dank fürs Zuschauen!", "您好,我是沙利沃。"]:
            with self.subTest(speech=speech):
                self.assertFalse(is_noise(speech))

    def test_prompt_echo(self):
        for echo in ["Polizei, Feuerwehr, Rettungsdienst, Schornsteinfeger.", "Hermes, DPD, UPS, GLS, FedEx", "Haustür-Sprechanlage.",
                     "Telekom, Vodafone."]:
            with self.subTest(echo=echo):
                self.assertTrue(prompt_echo(echo))
        for real in ["Hallo, hier ist die Polizei, bitte öffnen Sie.", "Guten Tag, hier ist der Paketdienst von DHL.", "Polizei!",
                     "Hier ist die Nachbarin von oben."]:
            with self.subTest(real=real):
                self.assertFalse(prompt_echo(real))


if __name__ == "__main__":
    unittest.main()
