"""Regex building blocks shared by the rules and the LLM guards.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

import re  # noqa: F401

L = r"[^\W\d_]"                                   # a letter of any alphabet ("Zoë", "Nguyễn", "Yılmaz")
W = L                                             # (kept for callers)
WORD = rf"{L}+(?:['’-]{L}+)*"
UP = "A-ZÄÖÜÀ-ÖØ-ÞŁŚŹŻČĆĐŠŽĞŞİŐŰĂȘȚ"
CAP = rf"(?-i:[{UP}]){L}*(?:-(?-i:[{UP}]){L}+)?"   # a capitalised word, even under re.I
ORGNAME = rf"(?-i:[{UP}])[\w&.-]*"                 # "DHL", "Amazon", "Stadtwerke", "E.ON"
ARTICLE = r"(?:der|die|das|dem|den|de|da|ein|eine|einer|ihr|ihre|ihrem|dein|deine|euer|eure|mein|meine|unser|unsere|the|a|an|your)"
GREETING = (r"(?:hallo|hallöchen|huhu|juhu|hier(?=\s*,)|hi|hey|moin(?: moin)?|servus|grüß gott|grüezi|guten (?:tag|morgen|abend)|tag|hello|na|"
            r"good (?:morning|afternoon|evening)|ja|also|okay|ok|merhaba|selam|salam|buongiorno|ciao|bonjour|hola|"
            r"dzień dobry|dobryj den|dobry den|privet|entschuldigung|sorry|excuse me)")
LEAD = r"(?:(?:\b" + GREETING + r")\b[\s,.!?]*)*"     # optional greetings before the introduction
FILLERS = r"(?<!\w)(?:ä+h+m*|ö+h+m*|hm+|mhm|e+h+m+|em)(?!\w)[,.]?\s*"
