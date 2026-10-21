"""The model never decides what is said: a take is written back and compared with the text; extra words after the text are
cut off, a wrong start or missing words mean another take, and after three bad takes nothing is spoken. Cases from the
live check on 21.10. (the model babbled on after the sentence)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from aikos_tts.engine import TEMPERATURES, FakeEngine, SpeechError
from aikos_tts.verify import Heard, Verdict, judge


def heard(*words_and_times):
    """("moment", 0.0, 0.4), ... → Heard list."""
    return [Heard(w, s, e) for w, s, e in words_and_times]


def spaced(text: str, gap: float = 0.1, length: float = 0.3, start: float = 0.2):
    out, t = [], start
    for w in text.lower().replace(",", "").replace(".", "").split():
        out.append((w, t, t + length))
        t += length + gap
    return out


def test_a_faithful_take_is_kept_whole():
    v = judge("Komme sofort.", heard(*spaced("komme sofort")), 1.5)
    assert v.ok and v.cut_s is None and v.coverage == 1.0


def test_babbling_after_the_text_is_cut_off():
    """Live: "Moment bitte, ich bin gleich bei Ihnen." + "Die Cards eint einer Eingammern ...". """
    words = spaced("moment bitte ich bin gleich bei ihnen") + [("die", 4.0, 4.2), ("cards", 4.3, 4.7), ("eint", 4.8, 5.0)]
    v = judge("Moment bitte, ich bin gleich bei Ihnen.", heard(*words), 6.0)
    last_end = spaced("moment bitte ich bin gleich bei ihnen")[-1][2]
    assert v.ok and v.cut_s == pytest.approx(last_end + 0.25)


def test_the_cut_never_reaches_into_the_next_word():
    words = spaced("komme sofort") + [("ihr", 1.0, 1.2)]
    v = judge("Komme sofort.", heard(*words), 2.0)
    assert v.ok and v.cut_s == pytest.approx(1.0)                  # sofort ends at 0.9, "ihr" starts at 1.0


def test_missing_words_or_a_wrong_start_mean_another_take():
    assert not judge("Bitte legen Sie das Paket in die graue Box.", heard(*spaced("bitte legen sie")), 2.0).ok
    assert not judge("Komme sofort.", heard(*spaced("ihr da hallo komme sofort")), 3.0).ok      # invented start
    assert not judge("Bitte kommen Sie.", heard(*spaced("gah bitte kommen sie")), 3.0).ok         # live: "Gah, bitte ..."
    assert not judge("Komme sofort.", [], 1.0).ok
    assert not judge("", heard(*spaced("hallo")), 1.0).ok


def test_an_inflected_word_counts_and_the_repeat_after_it_is_cut():
    """Live 21.10. 23:56: "Hinfort, sie Schelm." was heard as "hinfort sie schelmen sie schelmen" three times, so nothing
    was said. The inflected form counts; the repeat after it is cut off."""
    words = spaced("hinfort sie schelmen sie schelmen")
    v = judge("Hinfort, sie Schelm.", heard(*words), 3.0)
    assert v.ok and v.cut_s == pytest.approx(words[3][1])                 # where the repeated "sie" starts


def test_short_or_different_words_are_not_taken_as_inflections():
    from aikos_tts.verify import same_word
    assert same_word("schelm", "schelmen") and same_word("komme", "kommen") and same_word("paket", "pakete")
    assert not same_word("an", "and") and not same_word("tür", "türen")        # under 4 letters: must be the same
    assert not same_word("komm", "kommission") and not same_word("tür", "tor")


def test_one_word_heard_differently_is_still_fine():
    v = judge("Wir sind gerade im Garten. Bitte kommen Sie hinten herum.",
              heard(*spaced("wir sind gerade im garten bitte kommen sie hintern herum")), 5.0)
    assert v.ok and v.coverage >= 0.85


class ScriptedChecker:
    """Says ok/not ok per take, as a whisper check would."""

    def __init__(self, verdicts):
        self.verdicts = list(verdicts)
        self.checked = []

    def check(self, expected, pcm, rate):
        self.checked.append(expected)
        return self.verdicts.pop(0)


def ref(tmp_path) -> Path:
    p = tmp_path / "v1" / "ref.wav"
    p.parent.mkdir()
    p.write_bytes(b"x")
    return p


def test_engine_retries_less_freely_and_cuts(tmp_path):
    checker = ScriptedChecker([Verdict(False, None, 0.5, "x"), Verdict(True, 0.1, 1.0, "komme sofort"),
                               Verdict(True, None, 1.0, "komme sofort")])                  # the cut take checked again
    engine = FakeEngine(checker=checker)
    pcm = engine.synthesize("Komme sofort.", ref(tmp_path))
    assert engine.temperatures == list(TEMPERATURES[:2])             # the second take was a little less free
    assert len(pcm) == 2 * int(0.1 * engine.rate)                    # cut at 0.1 s
    samples = np.frombuffer(pcm, dtype="<i2")
    assert abs(int(samples[-1])) < 100                                # faded out, no click


def test_engine_says_nothing_after_three_bad_takes(tmp_path):
    checker = ScriptedChecker([Verdict(False, None, 0.2, "ihr")] * 3)
    engine = FakeEngine(checker=checker)
    with pytest.raises(SpeechError):
        engine.synthesize("Komme sofort.", ref(tmp_path))
    assert len(engine.temperatures) == 3


def test_every_sentence_is_checked_on_its_own(tmp_path):
    checker = ScriptedChecker([Verdict(True, None, 1.0, "a"), Verdict(True, None, 1.0, "b")])
    engine = FakeEngine(checker=checker)
    engine.synthesize("Hallo. Ich komme gleich.", ref(tmp_path))
    assert checker.checked == ["Hallo.", "Ich komme gleich."]


def test_whisper_tokens_become_words():
    """Live 21.10.: whisper.cpp gives tokens ("pak", "et", "gra", "ue"), not words."""
    from aikos_tts.verify import join_tokens
    seg = [(" Bitte", 0.0, 0.3), (" legen", 0.3, 0.6), (" das", 0.6, 0.7), (" Pak", 0.7, 0.9), ("et", 0.9, 1.1),
           (" in", 1.1, 1.2), (" die", 1.2, 1.3), (" gra", 1.3, 1.5), ("ue", 1.5, 1.7), (" Box", 1.7, 2.0), (".", 2.0, 2.1)]
    words = join_tokens([seg, [(" Ha", 2.5, 2.7), ("ust", 2.7, 2.9), ("ür", 2.9, 3.1), (",", 3.1, 3.2), (" ja", 3.3, 3.5)]])
    assert [w.word for w in words] == ["bitte", "legen", "das", "paket", "in", "die", "graue", "box", "haustür", "ja"]
    assert (words[3].start, words[3].end) == (0.7, 1.1)
    assert judge("Bitte legen das Paket in die graue Box.", words[:8], 2.2).ok


def test_a_cut_take_that_still_has_extra_words_is_made_again(tmp_path):
    """Live: "Komme sofort. Sofort" - the first cut was a little late."""
    checker = ScriptedChecker([Verdict(True, 0.5, 1.0, "komme sofort sofort"), Verdict(True, 0.45, 1.0, "komme sofort so"),
                               Verdict(True, None, 1.0, "komme sofort")])
    engine = FakeEngine(checker=checker)
    engine.synthesize("Komme sofort.", ref(tmp_path))
    assert engine.temperatures == list(TEMPERATURES[:2]) and len(checker.checked) == 3
