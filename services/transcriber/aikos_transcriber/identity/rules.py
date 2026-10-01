"""Rules: self-introductions and announcements, deterministic and instant.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

import re

from .lexicon import FAMILY, NOT_NAMES, RELATION, STOP, TITLES
from .model import Identity, _Who
from .patterns import ARTICLE, CAP, GREETING, L, LEAD, ORGNAME, UP, WORD
from .roles import canon, org_of, role_label, role_of
from .text import clean

# introduction phrases → strength (the clearest introduction wins)
PHRASES = [
    (r"meine?\s+name\s+(?:ist|is)|ich\s+hei(?:ß|ss)e|hier\s+spricht|my\s+name\s+is|je\s+m['’]appelle|me\s+llamo|"
     r"mi\s+chiamo|nazywam\s+się|benim\s+adım", 3),
    (r"(?<!das\s)hier\s+(?:ist|sind|is)|this\s+is|it['’]s|c['’]est", 2),     # "das hier ist Anna" presents someone else
    (r"(?:ich|i|isch|icke|ick)\s+bin(?:['’]?s|\s+es|\s+et)?|wir\s+sind(?:['’]?s|\s+es)?|(?:ich|wir)\s+(?:komme|kommen)(?=\s+(?:von|vom|aus)\b)|"
     r"i\s+am|i['’]m|we\s+are|sono|je\s+suis|soy|jestem", 1),
]


# what may follow a role word at the start for it to be an announcement ("Polizei!", "Paket für …",
# "Die Handwerker sind da", "Gerichtsvollzieher Braun, …") rather than the subject of a sentence ("Das Paket ist kaputt")
AFTER_ROLE = (rf"(?:\s+(?:von|vom|from)\s+(?:(?:der|dem|den|the)\s+)?(?P<org>{ORGNAME}(?:\s+{ORGNAME})?))?"
              rf"(?:,?\s+(?!{ARTICLE}\s)(?P<name>{CAP}(?:\s+{CAP})?))?"
              r"(?=\s*(?:$|[,.!?;:–-]|für\b|hier\b|ist da\b|sind da\b|mit\b|for\b|here\b|is here\b))")
# a courier saying what they bring, anywhere in the utterance ("ich habe ein Paket für Sie", "isch habe Paket für Nachbar")
BRING = (r"\b(?:ich|isch|wir)\s+(?:habe|hab|hätte|bringe|bring|haben|bringen)\s+(?:(?:ein|eine|einen|zwei|drei|vier|\d+)\s+)?"
         r"(?P<what>pakete?|päckchen|sendung(?:en)?|lieferung|einschreiben)\w*\s+(?:für|abzugeben|bringen)\b"
         r"(?![^,.!?]*\b(?:angenommen|bekommen|abgeholt|verloren)\b)"
         r"|\b(?:ich|isch)\s+(?:pakete?|päckchen)\s+(?:bringen|bringe|abgeben|liefern)\b")


def lead(text: str) -> tuple[str, str, str, str]:
    """(role id, company, matched word, name) announced at the very start: "Amazon, ich stelle …",
    "Hallo, Paket für …", "Polizei, bitte öffnen", ", Ihre Nachbarin", "Paket von Amazon", "Gerichtsvollzieher Braun, …".
    A role word or company later in a sentence is only a topic ("beim Nachbarn abgeben", "die Polizei rufen",
    "mein Paket von Amazon", "Das Paket von Amazon ist beschädigt")."""
    m = re.match(r"\s*[,.!?;:–-]*\s*" + LEAD + rf"(?:{ARTICLE}\s+)?(?P<w1>{WORD})(?:\s+(?P<w2>{WORD})(?:\s+(?P<w3>{WORD}))?)?",
                 text, re.I)
    if not m:
        return "", "", "", ""
    w1, w2, w3 = m.group("w1"), m.group("w2") or "", m.group("w3") or ""
    for cand in (f"{w1} {w2} {w3}", f"{w1} {w2}", w1, w1.split("-")[0]):   # "Essen auf Rädern"   # a company up front is an announcement ("Amazon-Lieferung")
        org, rid = org_of(cand)
        if org:
            return rid, org, cand, ""
    rid = role_of(w1)
    if not rid:
        return "", "", "", ""
    after = re.match(AFTER_ROLE, text[m.start("w1") + len(w1):], re.I)
    if not after:
        return "", "", "", ""
    org = ""
    if after.group("org"):
        org, _ = org_of(after.group("org"))
        org = org or after.group("org")
    name = after.group("name") or ""
    if name and (name.split()[0].lower() in STOP | NOT_NAMES or role_of(name.split()[0]) or org_of(name)[0]):
        org = org or org_of(name)[0]
        name = ""
    return rid, org, w1, name


def brings(text: str) -> tuple[str, str]:
    """A courier describing the delivery anywhere: (role id, company said in the first words)."""
    m = re.search(BRING, text, re.I)
    if not m:
        return "", ""
    what = (m.group("what") or "").lower()
    rid = "mail" if what in ("einschreiben", "brief") else "parcel"
    for w in re.findall(WORD, text)[:14]:
        org, org_rid = org_of(w)
        if org:
            return org_rid, org
    return rid, ""


# a speaker correcting themselves: "DPD, äh, nee, GLS", "Mar... Marion", "Jens hier, Jan! Jan, sorry"
CORRECTION = r"(?:\.\.\.|…|\b(?:nee|nein|quatsch|sorry|ich meine|also|pardon)\b)[\s,.!]*"


def corrected(text: str) -> str:
    """If the speaker corrects a name/company right at the start, keep only the correction."""
    m = re.match(rf"(?P<pre>.{{0,60}}?)(?:{CORRECTION})+(?P<rest>(?!(?:nee|nein|quatsch|sorry|also|pardon)\b)\S.*)",
                 text, re.I | re.S)
    if m and re.search(rf"(?-i:[{UP}])\w*", m.group("pre")) and len(re.findall(WORD, m.group("pre"))) <= 6:
        lead_words = re.findall(WORD, m.group("rest"))[:1]
        if re.match(r"(?:hier ist|hier sind|ich bin|mein name ist|ich heiße)\b", m.group("rest"), re.I):
            return (re.match(r"\s*" + LEAD, m.group("pre"), re.I).group(0) + m.group("rest")).strip()   # "Nein, ich bin's, Jonas"
        if lead_words and (org_of(lead_words[0])[0] or role_of(lead_words[0]) or lead_words[0][0].isupper()):
            greet = re.match(r"\s*" + LEAD, m.group("pre"), re.I).group(0)
            intro = re.search(r"\b(?:hier ist|hier sind|ich bin|mein name ist|ich heiße)\b", m.group("pre"), re.I)
            return (greet + (intro.group(0) + " " if intro else "") + m.group("rest")).strip()
    return text


def _message(text: str, span: tuple[int, int] | None) -> str:
    if span is None:
        rest = text
    else:
        rest = text[: span[0]] + " " + text[span[1]:]
        rest = re.sub(r"^\s*" + LEAD, "", rest, flags=re.I)         # greeting left in front
    rest = re.sub(r"\s+([,.!?])", r"\1", rest)
    rest = re.sub(r"([,.!?])(?:\s*[,])+", r"\1", rest)              # "Oma,, ich" → "Oma, ich"
    rest = re.sub(r",\s*([.!?])", r"\1", rest)                        # "Hilfe,!" → "Hilfe!"
    rest = re.sub(r"\b(und|oder|aber),", r"\1", rest)                  # "Anna, und, wir" → "Anna, und wir"
    rest = re.sub(r"^[\s,.!?;:–-]+|[\s,;:–-]+$", "", " ".join(rest.split())).strip()
    rest = re.sub(r"^" + LEAD + r"$", "", rest, flags=re.I).strip()  # only a greeting left
    if not re.search(L + r"{2,}", rest):
        return ""
    return rest[0].upper() + rest[1:]


def _compose(name: str, rid: str, org: str, matched: str = "") -> str:
    if rid == "relation":
        return role_label(rid, matched) + (f" von {org}" if org else "")
    tail = org or (role_label(rid, matched) if rid else "")
    if name:
        return f"{name} · {tail}" if tail else name
    if rid and org and org != role_label(rid):
        return org if rid in ("telecom", "utility") else f"{role_label(rid, matched)} · {org}"
    return tail


# ── rules ─────────────────────────────────────────────────────────────────────
TOKEN = re.compile(rf"{WORD}|[,.!?;:…–]")


def parse_who(text: str, pos: int, known: dict) -> _Who | None:
    """Read who is named at text[pos:]: [article] [titles] Name(s) [und Name(s)] | Role [Name] [von Org|nebenan]."""
    toks = [(m.group(0), pos + m.start(), pos + m.end()) for m in TOKEN.finditer(text[pos:pos + 160])]
    i, n = 0, len(toks)

    def word(k):
        return k < n and re.fullmatch(WORD, toks[k][0]) is not None

    def cap(k):
        return word(k) and toks[k][0][0].isupper() and toks[k][0].lower() not in STOP

    possessive = word(i) and re.fullmatch(r"mein|meine|dein|deine|ihr|ihre|euer|eure|unser|unsere|your|my", toks[i][0], re.I)
    if word(i) and re.fullmatch(ARTICLE, toks[i][0], re.I):
        i += 1
    for _ in range(2):                                       # "der neue Vermieter", "die zuständige Hebamme"
        if word(i) and re.fullmatch(r"(?-i:[a-zäöüß])+(?:e|en|er|es)", toks[i][0]) and cap(i + 1):
            i += 1
    start_i = i
    titles, names, rid, org, matched, end = [], [], "", "", "", None
    while word(i) and toks[i][0].lower().rstrip(".") in TITLES:
        titles.append(toks[i][0]); end = toks[i][2]; i += 1
        if i < n and toks[i][0] == "." and titles[-1].lower() in ("dr", "prof"):
            titles[-1] += "."; i += 1
    if cap(i) and not titles and (role_of(toks[i][0]) or org_of(toks[i][0])[0]):
        matched = toks[i][0]
        org, org_rid = org_of(matched)
        if i + 1 < n and word(i + 1) and org_of(f"{matched} {toks[i + 1][0]}")[0]:       # "Deutsche Post", "Uber Eats"
            org, org_rid = org_of(f"{matched} {toks[i + 1][0]}"); i += 1
        rid = role_of(matched) or org_rid
        end = toks[i][2]; i += 1
        if not org and i + 1 < n and toks[i][0] == "," and word(i + 1) and org_of(toks[i + 1][0])[0]:
            org = org_of(toks[i + 1][0])[0]; end = toks[i + 1][2]; i += 2            # "Paketbote, Hermes"
        k = i + 1 if i < n and toks[i][0] == "," else i                                    # "Nachbar, Klaus"
        while cap(k) and len(names) < 2 and not role_of(toks[k][0]) and toks[k][0].lower() not in NOT_NAMES:
            names.append(toks[k][0]); end = toks[k][2]; k += 1
        if names:
            i = k
    else:
        while cap(i) and len(names) < 3 and not role_of(toks[i][0]) and not org_of(toks[i][0])[0]:
            names.append(toks[i][0]); end = toks[i][2]; i += 1
        if names and word(i) and toks[i][0].lower() == "und" and cap(i + 1):                # "Anna und Jonas"
            more = []
            k = i + 1
            while cap(k) and len(more) < 3 and not role_of(toks[k][0]):
                more.append(toks[k][0]); k += 1
            if more:
                names += ["und"] + more; end = toks[k - 1][2]; i = k
        if names and names[0].lower() in NOT_NAMES and not titles:
            return None
        if names and names[0].lower() in RELATION and not titles:
            rid, matched, names = "relation", names[0], []   # shown as said: "Bruder", "Freund von Tom", "Student"
        if names and len(names) == 1 and not titles and re.search(r"(?:ung|heit|keit|schaft|tion|tät|ismus)$", names[0]):
            return None                                      # "ich bin der Meinung": an abstract noun, not a name
        if names and possessive and names[0].lower() not in FAMILY and names[0].lower() not in RELATION:
            return None                                      # "Hier ist mein Pass" (but "Hier ist dein Papa", "dein Bruder")
        if names and len(names) == 1 and len(names[0]) < 2:
            return None                                      # "ich bin M, …": a stray letter is no name
        if not names and titles:
            return None
    # "… von DHL", "… vom Pflegedienst", "… von nebenan", "… von den Zeugen Jehovas"
    if word(i) and toks[i][0].lower() in ("von", "vom", "aus", "from"):
        k = i + 1
        if word(k) and toks[k][0].lower() in ("der", "dem", "den", "the"):
            k += 1
        if word(k) and toks[k][0].lower() in ("nebenan", "oben", "unten", "gegenüber", "drüben"):
            rid = rid or "neighbour"; end = toks[k][2]
        elif cap(k):
            words = [toks[k][0]]
            while cap(k + len(words)) and len(words) < 3 and not org_of(toks[k][0])[0]:
                words.append(toks[k + len(words)][0])
            phrase = " ".join(words)
            o, orid = org_of(phrase)
            if not o and len(words) > 1:
                o, orid = org_of(words[0])
                words = words[:1] if o else words
            if o:
                org, rid = o, rid or orid
            elif role_of(words[0]):
                rid = rid or role_of(words[0])                   # "von den Stadtwerken"
            elif names or rid or i == start_i:
                org = org or " ".join(words)                     # an unknown company, as said
                rid = rid or role_of(words[-1])
            end = toks[k + len(words) - 1][2]
            matched = matched or words[0]
    if not names and not rid and not org:
        return None
    name = " ".join(titles + names)
    return _Who(known.get(name.lower(), name), rid, org, matched, end)


def by_rules(text: str, known_names=(), side: str = "door") -> Identity:
    text = clean(text)
    fixed = corrected(text)
    if fixed != text:                                  # the speaker corrected themselves: try the correction first
        ident = _rules(fixed, known_names, side)
        if ident.speaker:
            return ident
    return _rules(text, known_names, side)


def _rules(text: str, known_names=(), side: str = "door") -> Identity:
    known = {n.lower(): n for n in known_names}
    found = []                                                   # (strength, -start, _Who, start)
    for pat, strength in PHRASES:
        for m in re.finditer(rf"(?<!\w)(?:{pat})(?!\w)[\s,]*", text, re.I):
            who = parse_who(text, m.end(), known)
            if who and strength == 1 and re.match(rf"\s+(?-i:[a-zäöüß]){L}*en\b", text[who.end:]) and \
                    not re.match(r"\s+(?:und|oder|aber|von|vom|aus|wegen|hier|gleich|jetzt)\b", text[who.end:], re.I):
                who = None                                       # "ich bin Oma besuchen" = I'm off visiting Oma
            if who:
                found.append((strength, -m.start(), who, m.start()))
    # Bavarian/Austrian "der Huber Franz, …" and family "die Omi ist da!" at the very start (door)
    m = re.match(r"\s*(?:hoho|haha|juhu|hey)?[\s,!]*" + LEAD + rf"(?:der|die|de|da)\s+(?P<w>{CAP}(?:\s+{CAP})?)(?=\s*(?:[,.!]|ist da\b|is da\b))",
                 text, re.I)
    if m and side == "door":
        who = parse_who(text, m.start("w"), known)
        if who and who.name and not who.rid and not who.org and \
                (len(who.name.split()) == 2 or who.name.lower() in FAMILY or re.match(r"\s+ist da\b", text[who.end:], re.I)
                 or len(re.findall(WORD, text)) <= 3):
            if re.match(r"\s+i?st da\b", text[who.end:], re.I):
                who.end = m.start("w")                           # keep "Omi ist da!" as the message
            found.append((1, -m.start(), who, m.start()))
    # "von Bülow hier" (name particles)
    for m in re.finditer(rf"(?:^|(?<=[,.!?]\s)|(?<=^\w{{0}}))(?:{GREETING}[\s,]+)?(?P<w>(?:von|van|de|zu)\s+{CAP})\s+hier(?!\w)", text, re.I):
        found.append((2, -m.start(), _Who(m.group("w"), "", "", "", m.end()), m.start("w")))
    # "Anna hier", "DHL hier" — not in a question ("Wohnt hier Herr Özdemir?")
    for m in re.finditer(rf"(?:^|(?<=[,.!?]\s))(?P<w>(?:{ARTICLE}\s+)?{WORD}(?:\s+{WORD}){{0,2}})\s+hier(?=\s*(?:[,.!:;–-]|$))", text, re.I):
        clause_end = re.search(r"[.!?]|$", text[m.end():])
        if text[m.end() + clause_end.start():m.end() + clause_end.end()] == "?":
            continue
        if re.match(r"(?:von|van|zu|de)\s", m.group("w")):
            continue                                             # "von Bülow hier": see name particles below
        who = parse_who(text, m.start("w"), known)
        if who and who.end == m.end("w"):
            who.end = m.end()
            found.append((2, -m.start(), who, m.start()))
    # "Kowalski mein Name", "Weber ist mein Name"
    for m in re.finditer(rf"(?:^|(?<=[,.!?]\s))(?P<w>{WORD}(?:\s+(?!ist\b){WORD})?),?\s+(?:ist\s+)?mein\s+name(?!\w)", text, re.I):
        who = parse_who(text, m.start("w"), known)
        if who and who.end == m.end("w"):
            who.end = m.end()
            found.append((3, -m.start(), who, m.start()))
    # from a room, a resident answers with the surname: "Wagner, hallo?", "Ja, Schmidt?"
    if side == "room" and len(re.findall(WORD, text)) <= 4:
        m = re.fullmatch(rf"\s*(?:ja,?\s*)?(?P<w>{CAP})\s*(?:,\s*(?:hallo|ja|guten tag))?\s*[?!.]*\s*", text, re.I)
        if m and m.group("w").lower() not in STOP | NOT_NAMES and not role_of(m.group("w")):
            found.append((2, 0, _Who(m.group("w"), "", "", "", m.end()), 0))

    if side == "room":                               # a resident: only a name counts, never a role or company
        found = [(s, p, w if w.rid == "relation" and not w.name else _Who(w.name, "", "", "", w.end), st)
                 for s, p, w, st in found if w.name or w.rid == "relation"]          # "Ich bin der Sohn" is fine too
    if found:
        strength, _, best, start = max(found, key=lambda f: (f[0], f[1]))
        name, rid, org, matched = best.name, best.rid, best.org, best.matched
        if not name and rid and side == "door":      # "Ihre Nachbarin hier, die Frau Schmitz"
            ap = re.match(r"\s*,\s*", text[best.end:])
            w = parse_who(text, best.end + ap.end(), known) if ap else None
            if w and w.name and not w.rid and not w.org and w.name.split()[-1].lower() not in NOT_NAMES:
                name = w.name
                best.end = w.end
        if side == "door":                           # a name and a role said separately belong together
            for _, _, w, _ in sorted(found, key=lambda f: -f[1]):
                if w is best:
                    continue
                if name and not (rid or org) and (w.rid or w.org) and not w.name:
                    rid, org, matched = w.rid, w.org, w.matched
                elif not name and w.name and (not w.rid or w.rid == rid):
                    name = w.name
            if name and not (rid or org):
                rid, org, matched, _ = lead(text[best.end:])                # "hier ist Anna, Ihre Nachbarin"
            if name and not (rid or org) and start > 0:
                rid, org, matched, _ = lead(text[:start])                   # "Physiotherapie, ich bin Tim"
        kind = "name" if name else "role"
        return Identity(speaker=_compose(name, rid, org, canon(matched)), kind=kind, name=name, role=rid, org=org,
                        message=_message(text, (start, best.end)), method="rules")
    if side == "room":
        return Identity(message=_message(text, None))
    # no introduction: a company or role word up front ("Amazon, ich stelle es …", "Paket für Schmidt")
    rid, org, matched, name = lead(text)
    if rid and not org and rid in ("parcel", "food", "mail"):
        org = brings(text)[1]
        if not org:
            for w in re.findall(WORD, text)[:8]:
                org = org_of(w)[0] or org
    if rid:
        return Identity(speaker=_compose(name, rid, org, matched), kind="name" if name else "role", name=name, role=rid,
                        org=org, message=_message(text, None), method="rules")
    rid, org = brings(text)                                                 # "isch habe Paket für Nachbar"
    if rid:
        return Identity(speaker=_compose("", rid, org), kind="role", role=rid, org=org,
                        message=_message(text, None), method="rules")
    return Identity(message=_message(text, None))
