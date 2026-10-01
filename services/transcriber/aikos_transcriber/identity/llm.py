"""Optional: the local LLM (Ollama), asked only when the rules find nobody; its answer is guarded.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

import json
import re
import urllib.request

from .lexicon import FAMILY, NOT_NAMES, STOP
from .model import Identity
from .patterns import ARTICLE, LEAD, WORD
from .roles import ROLES, org_in, role_of
from .rules import _compose, _message, brings

# ── optional: local LLM (Ollama) when the rules find nothing ──────────────────
LLM_PROMPT = """Du bekommst das Transkript EINER Äußerung an einer Haustür-Sprechanlage (meist Deutsch, oft mit Akzent,
Dialekt oder Fehlern der Spracherkennung). %s
Frage: Sagt die SPRECHENDE Person, wer SIE SELBST ist – ihren Namen, ihre Firma, Behörde oder Funktion?
Regeln:
- Nur Selbstvorstellungen zählen. Angesprochene, gesuchte oder erwähnte Personen zählen NICHT ("Mama, mach auf",
  "Mia, da ist jemand", "Ist Anna da?", "Ich suche Herrn Müller", "Guten Tag, Frau Doktor Weber", "Tom hat gesagt …",
  "Grüße von Tom", "Die Hebamme kommt um zehn").
- Empfänger zählen nicht: bei "Paket für Schmidt" ist der Sprecher der Paketdienst, nicht Schmidt.
- Themen zählen nicht: "Soll ich die Polizei rufen?", "beim Nachbarn abgeben", "das Paket von Amazon ist kaputt".
- Pronomen ("ich", "wir") sind keine Antwort. Im Zweifel: niemand.
- "speaker" wörtlich aus dem Transkript übernehmen (Name, Firma oder Funktion), nichts erfinden, nichts übersetzen.
Beispiele:
"Merhaba, ich Mehmet von oben, haben Sie Salz?" → {"speaker": "Mehmet", "kind": "name", "role": "neighbour"}
"Guten Tag, Stadtreinigung, wir müssen an die Mülltonnen." → {"speaker": "Stadtreinigung", "kind": "role", "role": ""}
"Habt ihr ein Paket für die Nachbarn angenommen?" → {"speaker": "", "kind": "none", "role": ""}
"Guten Tag, eine kurze Umfrage zur Bundestagswahl." → {"speaker": "", "kind": "none", "role": ""}
"Mama, mach auf, ich bin's!" → {"speaker": "", "kind": "none", "role": ""}
"Mia, da ist jemand an der Tür für dich." → {"speaker": "", "kind": "none", "role": ""}
"Guten Tag, Frau Doktor Weber, ich habe einen Termin." → {"speaker": "", "kind": "none", "role": ""}
"Icke bin's, der Kalle, mach ma uff." → {"speaker": "Kalle", "kind": "name", "role": ""}
"Das ist Anna, sie ist neu in der Klasse." → {"speaker": "", "kind": "none", "role": ""}
"I'm here for the apartment viewing." → {"speaker": "", "kind": "none", "role": ""}
Antworte nur mit JSON: {"speaker": "...", "kind": "name"|"role"|"none", "role": "<eine von: %s oder leer>"}"""
SIDE_HINT = {"door": "Sie kommt von der HAUSTÜR (Besuch, Lieferdienst, Behörde …).",
             "room": "Sie kommt aus einem ZIMMER: Es spricht jemand, der hier wohnt. Nur ein Name kann zählen; "
                     "Lieferdienste, Handwerker usw. sind dann nur Thema."}
THIRD_PERSON = (r"hat|hatte|ist|war|sagt|sagte|meinte|erzählte|kommt|kam|wird|will|möchte|lässt|grüßt|wartet|schläft|arbeitet|braucht|"
                r"steht|sitzt|holt|bringt|ruft|meint|weiß|kann|muss|soll|darf|wohnt")


def by_llm(text: str, url: str, model: str, timeout: float = 8.0, side: str = "door") -> Identity | None:
    body = {"model": model, "stream": False, "think": False, "keep_alive": -1, "format": "json",   # stays loaded: no cold start
            "options": {"temperature": 0},
            "messages": [{"role": "system", "content": LLM_PROMPT % (SIDE_HINT.get(side, ""), ", ".join(ROLES))},
                         {"role": "user", "content": text}]}
    req = urllib.request.Request(url.rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        ans = json.loads(json.loads(r.read())["message"]["content"])
    speaker = str(ans.get("speaker") or "").strip().strip(",.!?")
    kind = ans.get("kind")
    if not speaker or kind not in ("name", "role") or (side == "room" and kind != "name"):
        return None
    # guards: the LLM may only point at words that are really in the transcript, and never at somebody addressed,
    # mentioned or talked about, or at a thing ("Paket", "… zur Bundestagswahl", "Spenden für das Tierheim")
    i = text.lower().find(speaker.lower())
    if i < 0 or re.fullmatch(r"(?:pakete?|päckchen|sendung|lieferung|einschreiben|briefe?|post)", speaker, re.I):
        return None
    before, after = text[:i], text[i + len(speaker):]
    if speaker.split()[0].lower() in STOP or speaker.lower() in NOT_NAMES:
        return None                                                   # a pronoun or a thing is nobody
    if re.fullmatch(r"\s*" + LEAD + rf"(?:{ARTICLE}\s+)?", before, re.I) and re.match(r"\s*,", after) and \
            (re.fullmatch(r"(?:frau|herr|herrn|dr\.?|doktor)\b.*", speaker, re.I) or
             re.match(r"\s*,\s*(?:\w+\s+){0,3}?(?:du|dich|dir|ihr|euch|mach|komm|kannst|hast|bist|schau|guck|da ist|"
                      r"es hat|es klingelt|jemand)\b", after, re.I)):
        return None                                                   # "Guten Tag, Frau Weber, …", "Mia, da ist jemand"
    if re.match(rf"\s+(?:{THIRD_PERSON})\b", after, re.I) and not re.search(r"(?:hier ist|ich bin|hier spricht)\s+(?:\w+\s+)?$",
                                                                            before, re.I):
        return None                                                   # "Tom hat gesagt", "Die Hebamme kommt um zehn"
    clause_end = re.search(r"[,.!?]|$", after)
    clause = before[max(before.rfind(c) for c in ",.!?") + 1:] + speaker + after[:clause_end.end()]
    intro_here = re.search(r"\b(?:ich bin|hier ist|hier sind|wir sind|mein name|ich heiße|ich komme)\b", clause, re.I)
    if clause.rstrip().endswith("?") and not intro_here:
        return None                                                   # "Haben Sie Internet von der Telekom?"
    if re.search(r"\b(?:ob|dass|weil|wenn|falls)\b[^,.!?]*$", before, re.I):
        return None                                                   # "…, ob das Ordnungsamt bei Ihnen war"
    if re.search(r"\b(?:habe|hab|haben|hat|rufe|rufen|ruf|hole|holen|frage|fragen|suche|suchen|kenne|kennen)\s+"
                 r"(?:(?:die|den|der|das|ein|eine|einen)\s+)?(?:\w+\s+)?$", before, re.I):
        return None                                                   # "Ich habe die Polizei schon gerufen" (an object)
    if re.search(r"\bnicht\s+(?:(?:der|die|das|ein|eine|ihr|ihre)\s+)?$", before, re.I):
        return None                                                   # "Ich bin nicht der Postbote"
    if re.search(r"\bbin\s+$", before, re.I) and re.match(r"\s+(?-i:[a-zäöüß])\w*en\b", after):
        return None                                                   # "Ich bin Oma besuchen" = I'm off visiting Oma
    sentence_start = before[max(before.rfind(c) for c in ".!?") + 1:]
    if not intro_here and re.fullmatch(r"\s*" + LEAD + r"(?:\w+\?\s*)?", sentence_start, re.I) and re.match(r"\s*[,?!]", after) and (
            side == "room" or re.search(r"\b(?:du|dich|dir|ihr|euch|mach|komm|kannst|hast|bist|schau|guck|you|me in|open|let me)\b",
                                        after, re.I)):
        return None                                                   # "Lukas? Lukas, mach auf", "Sophie, welchen Knopf…"
    if (speaker.lower() in FAMILY or re.match(r"(?:frau|herr|herrn)\s", speaker, re.I)) and \
            not re.search(r"\b(?:ich bin|hier ist|mein name|ich heiße)\b[^.!?]*$", before, re.I) and \
            (side == "room" or (re.search(r",\s*$", before) and re.match(r"\s*,", after))):
        return None                                                   # "Post ist da, Mama, für dich …", "…, Herr Böck, …"
    if re.search(r"\bdas\s+(?:hier\s+)?ist\s+$", before, re.I) and \
            re.search(r"^[^.!?]*[.!?,]\s*(?:sie|er)\s+(?:ist|hat|will|möchte|kommt|wohnt|darf|kann)\b", after, re.I):
        return None                                                   # "Das ist Anna. Sie ist neu in der Klasse."
    if re.search(r"\bist\s+$", before, re.I) and re.match(r"\s+(?:da|zu hause|daheim|dahoam|zuhause)\b", after, re.I) or \
            re.match(r"\s+da\s+m[ıi]\b", after, re.I):
        return None                                                   # "Ist Ayşe zu Hause?", "Ayşe da mı?"
    if re.search(r",\s*$", before) and re.fullmatch(r"\s*[.!?]*\s*", after[:3]) and \
            not re.search(r"(?:ich bin['’]?s|ich bin es|hier ist|hier spricht|das ist|it['’]s|this is)\s*,\s*$", before, re.I):
        return None                                                   # "Ich bin zu Hause, Tom." addresses Tom
    if re.search(r"\b(?:für|zur|zum|wegen|über|an|auf|beim|bei|nach|mit|um|statt|anstatt|ohne|grüße von|gruß von|for|about|to|at)\s+"
                 r"(?:(?:der|die|das|den|dem|ein|eine|einen|einem)\s+)?$", before, re.I):
        return None
    if kind == "name" and re.search(r"\bvon\s+$", before, re.I) and not re.search(r"(?:ich bin|wir sind|komme)\b", before, re.I):
        return None                                                   # "Grüße von Tom"
    rid = ans.get("role") if ans.get("role") in ROLES else ""
    org, org_rid = org_in(speaker)
    if kind == "role" and (role_of(speaker) or org_rid):              # a known role word: same label as the rules
        rid = role_of(speaker) or org_rid
        if not org and rid in ("parcel", "food", "mail"):
            org = brings(text)[1]
        speaker = _compose("", rid, org, speaker)
    # shown as said: the LLM is only asked when the lists above know nothing about this visitor
    ident = Identity(speaker=speaker, kind=kind, name=speaker if kind == "name" else "", role=rid or org_rid, org=org,
                     method="llm")
    ident.message = _message(text, _clause_span(text, speaker))
    return ident


def _clause_span(text: str, speaker: str):
    """Span of the short clause that holds the introduction ("…, Stadtreinigung, …"); None if it is a long sentence."""
    for m in re.finditer(r"[^,.!?;]+[,.!?;]*", text):
        clause = m.group(0)
        if speaker.lower() in clause.lower():
            return m.span() if len(re.findall(WORD, clause)) <= 6 else None
    return None
