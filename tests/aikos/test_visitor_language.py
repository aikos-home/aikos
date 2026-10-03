"""R28 in the call log: the visitor's language per call, and the translation of a resident's answer for the door screen."""
import json

from custom_components.aikos.call_log import CallLog

EN = {"text": "Hallo, hier ist Anna von der Post.", "text_original": "Hello, this is Anna from the post office.",
      "language": "en", "language_name": "Englisch", "language_probability": 0.97, "speaker": "Anna"}


def started():
    log = CallLog()
    log.start("c1")
    return log


def test_a_clear_foreign_sentence_sets_the_language_for_the_call():
    log = started()
    log.add("door", "t1", EN)
    assert (log.visitor_language, log.visitor_language_name) == ("en", "Englisch")
    log.add("door", "t2", {"text": "Ja.", "language": "", "speaker": ""})          # a later short sentence changes nothing
    assert log.visitor_language == "en"


def test_unsure_or_short_never_switches():
    log = started()
    log.add("door", "t1", dict(EN, language_probability=0.6))
    log.add("door", "t2", dict(EN, text_original="Hello there."))                  # 2 words
    log.add("door", "t3", dict(EN, language="nl", language_name="Niederländisch", language_probability="kaputt"))
    assert log.visitor_language == ""


def test_the_pass_2_update_of_the_same_sentence_counts():
    log = started()
    log.add("door", "t1", {"text": "Guten Tag, ich habe ein Paket für Sie.", "language": ""})   # pass 1: no language yet
    assert log.visitor_language == ""
    log.add("door", "t1", {"text": "Guten Tag, ich habe ein Paket für Sie.", "text_original": "Iyi günler, size bir paketim var.",
                           "language": "tr", "language_name": "Türkisch", "language_probability": 0.93})
    assert (log.visitor_language, len(log.messages)) == ("tr", 1)


def test_clear_german_switches_back_and_a_call_end_resets():
    log = started()
    log.add("door", "t1", EN)
    log.add("door", "t2", {"text": "Ach so, ich kann auch Deutsch sprechen.", "language": "de", "language_probability": 0.95})
    assert log.visitor_language == ""
    log.add("door", "t3", EN)
    log.end()
    assert (log.visitor_language, log.visitor_language_name) == ("", "")
    log.add("door", "t4", EN)
    log.start("c2")
    assert log.visitor_language == ""


def test_a_resident_answer_carries_its_translation_for_the_door():
    log = started()
    log.add("door", "t1", EN)
    log.add("room", "t2", {"text": "Ich komme gleich runter.", "speaker": "", "device": "Key A"})
    assert "tr" not in log.messages[-1]                                              # German first, nothing extra yet
    log.add("room", "t2", {"text": "Ich komme gleich runter.", "speaker": "", "device": "Key A",
                           "text_visitor": "I'll be right down.", "visitor_language": "en"})
    shown = json.loads(log.feed_json())[-1]
    assert (len(log.messages), shown["text"], shown["tr"], shown["tr_lang"]) == (2, "Ich komme gleich runter.", "I'll be right down.", "en")
