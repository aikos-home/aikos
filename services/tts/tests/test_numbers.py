"""Numbers as German words (0.6.1): the model gets words, and the check counts "10" and "zehn" as the same. Live 22.10.:
"Prüfsatz um 10 Uhr 13." was not said, because the check compared digits with words."""

from __future__ import annotations

import pytest

from aikos_tts.engine import FakeEngine
from aikos_tts.numbers import spell, words
from aikos_tts.verify import Heard, join_tokens, judge


@pytest.mark.parametrize("n,w", [(0, "null"), (1, "eins"), (16, "sechzehn"), (20, "zwanzig"), (21, "einundzwanzig"),
                                 (30, "dreißig"), (99, "neunundneunzig"), (100, "einhundert"), (101, "einhunderteins"),
                                 (1234, "eintausendzweihundertvierunddreißig"), (2026, "zweitausendsechsundzwanzig")])
def test_cardinals(n, w):
    assert words(n) == w


@pytest.mark.parametrize("text,said", [
    ("Ich bin in 20 Minuten da.", "Ich bin in zwanzig Minuten da."),
    ("Prüfsatz um 10 Uhr 13.", "Prüfsatz um zehn Uhr dreizehn."),
    ("um 10:13 Uhr", "um zehn Uhr dreizehn"),
    ("Um 10:00 Uhr kommt er.", "Um zehn Uhr kommt er."),
    ("Es ist 10.13 Uhr.", "Es ist zehn Uhr dreizehn."),
    ("am 22.10. kommt das Paket", "am zweiundzwanzigsten zehnten kommt das Paket"),
    ("Am 22.10.2026", "Am zweiundzwanzigsten zehnten zweitausendsechsundzwanzig"),
    ("am 3. Oktober", "am dritten Oktober"),
    ("im 3. Stock", "im dritten Stock"),
    ("Wir kommen um 3. Dann gehen wir.", "Wir kommen um drei. Dann gehen wir."),
    ("2,5 Kilo", "zwei Komma fünf Kilo"),
    ("1 Paket", "ein Paket"),
    ("Zimmer 1.", "Zimmer eins."),
    ("Haus 12a", "Haus 12a"),
])
def test_spelled_out(text, said):
    assert spell(text) == said


def spaced(text, gap=0.1, length=0.3):
    out, t = [], 0.2
    for w in text.split():
        out.append((" " + w, t, t + length))
        t += length + gap
    return out


@pytest.mark.parametrize("heard", ["Prüfsatz um zehn Uhr dreizehn.", "Prüfsatz um 10 Uhr 13.", "Prüfsatz um 10.13 Uhr."])
def test_the_check_takes_digits_and_words_alike(heard):
    words_ = join_tokens([spaced(heard)])
    assert judge("Prüfsatz um 10 Uhr 13.", words_, 3.0).ok, [w.word for w in words_]


def test_a_date_heard_as_digits_or_words():
    for heard in ("Das Paket kommt am 22.10.", "Das Paket kommt am zweiundzwanzigsten Zehnten."):
        assert judge("Das Paket kommt am 22.10.", join_tokens([spaced(heard)]), 3.0).ok


def test_whisper_splits_a_time_into_tokens():
    seg = [(" Um", 0.0, 0.2), (" 10", 0.2, 0.5), (".", 0.5, 0.55), ("13", 0.55, 0.9), (" Uhr", 0.9, 1.1), (".", 1.1, 1.2)]
    assert [w.word for w in join_tokens([seg])] == ["um", "zehn", "uhr", "dreizehn"]
    assert judge("Um 10:13 Uhr.", join_tokens([seg]), 1.5).ok


def test_the_model_gets_words_and_a_date_is_not_cut_into_sentences(tmp_path):
    said = []
    engine = FakeEngine(on_call=lambda text, ref: said.append(text))
    ref = tmp_path / "ref.wav"
    ref.write_bytes(b"x")
    engine.synthesize("Das Paket kommt am 3. Oktober um 10:30 Uhr. Danke!", ref)
    assert said == ["Das Paket kommt am dritten Oktober um zehn Uhr dreißig.", "Danke!"]


def test_one_counts_however_it_is_read():
    assert judge("1 Paket liegt vor der Tür.", [Heard(w, i, i + 0.5) for i, w in
                                                enumerate(["eins", "paket", "liegt", "vor", "der", "tür"])], 4.0).ok
