"""Visitor types: roles, companies, content types, the urgent pattern, role labels.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

import difflib
import re

from .patterns import L

# ── roles: id → (label, keyword regexes). Case-insensitive unless the pattern starts with (?-i) ──
ROLES: dict[str, tuple[str, list[str]]] = {
    "parcel":    ("Paketdienst", [r"paket\w*", r"\w*zusteller\w*", r"kurier\w*", r"sendung\w*", r"parcel", r"delivery", r"courier"]),
    "mail":      ("Post", [r"(?-i:Post)", r"deutsche post", r"postbot\w*", r"briefträger\w*", r"postman", r"mailman"]),
    "food":      ("Lieferdienst", [r"lieferando", r"wolt", r"uber ?eats", r"pizza\w*", r"essenslieferung", r"lieferservice",
                                   r"lieferdienst", r"(?:ihr|dein|euer) essen", r"food delivery"]),
    "police":    ("Polizei", [r"polizei\w*", r"police", r"kommissar\w*"]),
    "fire":      ("Feuerwehr", [r"feuerwehr\w*", r"fire (?:department|brigade)"]),
    "ambulance": ("Rettungsdienst", [r"rettungs\w*", r"notarzt\w*", r"sanitäter\w*", r"krankenwagen", r"paramedic\w*", r"ambulance"]),
    "neighbour": ("Nachbar", [r"nachbar(?:in)?", r"von nebenan", r"neighbou?r"]),
    "trades":    ("Handwerker", [r"handwerker\w*", r"monteur\w*", r"installateur\w*", r"elektriker\w*", r"klempner\w*",
                                 r"techniker\w*", r"schlüsseldienst", r"dachdecker\w*", r"maler\w*", r"plumber", r"electrician",
                                 r"technician"]),
    "chimney":   ("Schornsteinfeger", [r"schornsteinfeger\w*", r"kaminkehrer\w*", r"bezirksschornsteinfeger\w*"]),
    "utility":   ("Stadtwerke", [r"stadtwerke\w*", r"wasserwerk\w*", r"zähler\w*", r"ablesung", r"netzbetreiber\w*",
                                 r"energieversorger\w*", r"\w*anbieter"]),
    "property":  ("Hausverwaltung", [r"hausverwaltung\w*", r"vermieter\w*", r"hausmeister\w*", r"landlord", r"caretaker"]),
    "care":      ("Pflegedienst", [r"pflegedienst\w*", r"pflegerin", r"pfleger", r"hebamme", r"physiotherap\w*", r"tierarzt\w*",
                                   r"ärztin", r"arzt"]),
    "taxi":      ("Taxi", [r"taxi\w*"]),
    "officials": ("Behörde", [r"ordnungsamt", r"zoll", r"gerichtsvollzieher\w*", r"(?-i:Amt)", r"behörde", r"\w+amt"]),
    "telecom":   ("Techniker", [r"glasfaser\w*", r"kabelanschluss"]),
    # voice v2 (R17.10): more visitor types; the RoomKey shows an icon per id
    "shopping":  ("Einkauf", [r"getränke\w*", r"einkäufe", r"einkaufs\w*", r"lebensmittel\w*"]),
    "pharmacy":  ("Apotheke", [r"apotheke\w*", r"botendienst", r"medikament\w*"]),
    "flowers":   ("Blumen", [r"blumen\w*", r"florist\w*", r"blumenlieferung"]),
    "freight":   ("Spedition", [r"spedition\w*", r"möbel\w*", r"umzugs\w*", r"umzug"]),
    "waste":     ("Müllabfuhr", [r"müll\w*", r"sperrmüll", r"stadtreinigung", r"abfall\w*"]),
    "household_help": ("Haushaltshilfe", [r"putzhilfe", r"putzfrau", r"reinigungskraft", r"haushaltshilfe", r"gärtner\w*",
                                          r"babysitter\w*", r"tagesmutter"]),
    "seasonal":  ("Sternsinger", [r"sternsinger\w*"]),
    "religion":  ("Glaubensgemeinschaft", []),       # only via ORGS ("Zeugen Jehovas") and content
    "campaign":  ("Wahlkampf", [r"kandidat\w*", r"wahlhelfer\w*", r"wahlkämpfer\w*"]),
}
# content → visitor type, for the icon only (not a speaker): door side, when nobody introduced themselves
CONTENT_TYPES: list[tuple[str, str]] = [
    ("kids_friend", r"\b(?:ein |eine )?(?:freund|freundin|kumpel) von\b|\baus (?:der|seiner|ihrer) klasse\b|\bzum spielen\b|\bkita\b"),
    ("sales", r"\b(?:spende\w*|sammeln für|umfrage|angebot|zeitungsabo|abonnement|energieberatung|stromvertrag|tarif\w*|"
              r"vertrag\w*|verkaufe\w*|lose)\b"),
    ("religion", r"\b(?:zeugen jehovas|bibel\w*|kirche\w*|gottes|glauben|gemeinde (?:christi|gottes))\b"),
    ("seasonal", r"\b(?:süßes oder saures|halloween|sankt martin|st\.? martin|nikolaus|sternsinger\w*|weihnachts\w*)\b"),
    ("campaign", r"\b(?:partei\w*|wahlkampf|wahlhelfer\w*|kandidat\w*|wahl\b|bundestagswahl|landtagswahl|kommunalwahl)\b"),
]
# somebody needs help — overrides quiet hours (R17.15); content, not an introduction
URGENT = (r"^\W*hilfe\b|\bhilfe\s*!|\b(?:brauche|brauchen) (?:dringend |sofort )?hilfe|\bhelfen sie mir\b|\bbitte helfen\b|"
          r"\bhilf mir\b|\bnotfall\b|\b(?:rufen sie|ruf|ruft) (?:bitte )?(?:einen |den |die )?(?:krankenwagen|notarzt|polizei|feuerwehr)\b|"
          r"\b(?:ist|bin|sind) (?:\w+ )?(?:gestürzt|bewusstlos|verletzt)\b|\bblutet\b|\bes brennt\b|\bfeuer\s*!|"
          r"\beinbrecher\w*|\beinbruch\b|\büberfall\w*|\bhelp\b|\bemergency\b|"
          r"\b(?:habe|hab|haben) (?:schon |bereits )?(?:die |den |einen )?(?:krankenwagen|notarzt|polizei|feuerwehr) "
          r"(?:schon |bereits )?(?:gerufen|angerufen|alarmiert)\b")
SELF_DECLARED = {"police", "officials", "utility", "trades"}   # "laut Besucher" (§2c): shown with a "?" badge
# companies → (display name, role id). Short acronyms are case-sensitive: "Ups!" is not UPS.
ORGS: list[tuple[str, str, str]] = [
    (r"(?-i:D\.?\s?H\.?\s?L\.?)", "DHL", "parcel"), (r"hermes", "Hermes", "parcel"), (r"(?-i:D\.?\s?P\.?\s?[DT]\.?)", "DPD", "parcel"),
    (r"(?-i:UPS)", "UPS", "parcel"), (r"(?-i:GLS)", "GLS", "parcel"), (r"fed ?ex", "FedEx", "parcel"),
    (r"amazon", "Amazon", "parcel"), (r"deutsche post", "Deutsche Post", "mail"),
    (r"lieferando", "Lieferando", "food"), (r"wolt", "Wolt", "food"), (r"uber ?eats", "Uber Eats", "food"),
    (r"flink", "Flink", "shopping"), (r"rewe", "Rewe", "shopping"), (r"hellofresh|hello fresh", "HelloFresh", "food"),
    (r"gorillas", "Gorillas", "shopping"), (r"picnic", "Picnic", "shopping"), (r"knuspr", "Knuspr", "shopping"),
    (r"fleurop", "Fleurop", "flowers"), (r"zeugen jehovas", "Zeugen Jehovas", "religion"),
    (r"essen auf rädern", "Essen auf Rädern", "food"),
    (r"telekom", "Telekom", "telecom"), (r"vodafone", "Vodafone", "telecom"),
    (r"vattenfall", "Vattenfall", "utility"), (r"(?-i:E\.ON|EnBW)", "E.ON", "utility"),
]


def _find(pattern: str, text: str):
    return re.search(r"(?<!\w)(?:" + pattern + r")(?!\w)", text, re.I)


VOCAB = ["paketdienst", "paketbote", "paketzusteller", "zusteller", "kurier", "sendung", "postbote", "briefträger",
         "lieferando", "lieferdienst", "lieferservice", "polizei", "feuerwehr", "rettungsdienst", "notarzt", "sanitäter",
         "krankenwagen", "nachbar", "nachbarin", "handwerker", "monteur", "installateur", "elektriker", "klempner",
         "techniker", "schlüsseldienst", "schornsteinfeger", "kaminkehrer", "stadtwerke", "ablesung", "hausverwaltung",
         "vermieter", "hausmeister", "pflegedienst", "hebamme", "physiotherapie", "ordnungsamt", "gerichtsvollzieher",
         "hermes", "amazon", "telekom", "vodafone", "vattenfall", "hellofresh"]


def canon(word: str) -> str:
    """Whisper's near-misses of doorstep words ("Stadttwerke", "Klemmer") → the word itself. Long words only."""
    if len(word) < 6 or not re.fullmatch(L + r"+", word):
        return word
    if any(re.fullmatch(p, word, re.I) for _, pats in ROLES.values() for p in pats):
        return word                                              # already a known word ("Gerichtsvollzieherin")
    m = difflib.get_close_matches(word.lower(), VOCAB, n=1, cutoff=0.84)
    return m[0].capitalize() if m and m[0] != word.lower() else word


def role_of(word: str) -> str:
    word = canon(word)
    for rid, (_, pats) in ROLES.items():
        if any(re.fullmatch(p, word, re.I) for p in pats):
            return rid
    for pat, _, rid in ORGS:
        if re.fullmatch(pat, word, re.I):
            return rid
    return ""


def org_in(text: str) -> tuple[str, str]:
    for pat, name, rid in ORGS:
        if _find(pat, text):
            return name, rid
    return "", ""


def org_of(phrase: str) -> tuple[str, str]:
    phrase = canon(phrase)
    for pat, name, rid in ORGS:
        if re.fullmatch(pat, phrase, re.I):
            return name, rid
    return "", ""


AS_SAID = {"trades", "care", "property", "officials", "ambulance", "chimney", "utility", "telecom", "mail", "fire", "freight"}   # "Hausmeister", "Gerichtsvollzieher", "Notarzt"


def role_label(rid: str, matched: str = "") -> str:
    if rid == "relation":
        return matched[:1].upper() + matched[1:]
    label = ROLES[rid][0]
    if rid == "neighbour" and matched.lower().endswith("in"):
        return "Nachbarin"
    matched = canon(matched) if matched else matched
    if rid in AS_SAID and matched and " " not in matched and not re.search(r"(?:en|ern)$", matched) or (
            rid in AS_SAID and matched.lower() in ("hausmeister", "handwerker", "techniker", "elektriker", "klempner")):
        return matched[0].upper() + matched[1:]
    return label
