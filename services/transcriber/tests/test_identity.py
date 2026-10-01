"""Who is speaking: the rule cases of roomkey's self-test (identity_cases.py) plus noise, prompt echo and speech checks."""
import unittest
from unittest import mock

import _path  # noqa: F401
import aikos_transcriber.identity as identity
from aikos_transcriber.identity import Identity, by_rules, classify, clean, is_caption, is_noise, prompt_echo, strip_captions
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

    def test_subtitle_credits_are_noise(self):
        # R24 (live 01.10. 23:06–23:10): a noise at the door came out as "ARD Text im Auftrag", 3 times, live too
        for noise in ["ARD Text im Auftrag", "ARD Text im Auftrag.", "ARD-Text im Auftrag von Funk", "ZDF für funk, 2017",
                      "Untertitel im Auftrag des ZDF für funk, 2017", "Untertitelung des ZDF, 2020", "Im Auftrag.",
                      "Videotext", "Copyright WDR 2021", "Text im Auftrag"]:
            with self.subTest(noise=noise):
                self.assertTrue(is_noise(noise))
        self.assertEqual(strip_captions("Hallo, hier ist die Post. ARD Text im Auftrag."), "Hallo, hier ist die Post.")

    def test_on_behalf_of_somebody_is_speech(self):
        # "im Auftrag" only counts as a caption with a broadcaster, or alone: a visitor says it about a company
        for speech in ["Guten Tag, ich komme im Auftrag der Stadtwerke wegen dem Zähler.",
                       "Ich bin im Auftrag der Hausverwaltung hier.", "Hier ist der Ableser, im Auftrag von Vodafone.",
                       "Standard Text"]:
            with self.subTest(speech=speech):
                self.assertFalse(is_noise(speech))
                self.assertEqual(strip_captions(speech), speech)

    def test_a_caption_is_never_the_speaker(self):
        for caption in ["ARD Text", "ARD", "das ZDF", "Funk", "Untertitel"]:
            with self.subTest(caption=caption):
                self.assertTrue(is_caption(caption))
        for person in ["Jonas", "Stadtwerke", "Paketdienst · DHL", "Frau Huber"]:
            with self.subTest(person=person):
                self.assertFalse(is_caption(person))
        # the LLM answered "ARD Text" as the speaker (R24): the visitor stays unknown, the words stay
        text = "Hallo, ist da jemand zu Hause, ich warte hier."
        with mock.patch.object(identity, "by_llm", return_value=Identity(speaker="ARD Text", kind="role", method="llm")):
            got = identity.identify(text, llm_url="http://127.0.0.1:9")
        self.assertEqual((got.speaker, got.kind, got.method), ("", "", ""))
        with mock.patch.object(identity, "by_llm", return_value=Identity(speaker="Greta", kind="name", name="Greta", method="llm")):
            self.assertEqual(identity.identify(text, llm_url="http://127.0.0.1:9").speaker, "Greta")   # a name still counts

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
