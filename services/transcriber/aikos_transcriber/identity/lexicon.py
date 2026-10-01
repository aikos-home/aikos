"""Word lists: words that are never a name, titles, family and relation words.

Part of the aikos transcriber (split from roomkey tools/talk_identity.py at d0d52b9, code unchanged).
"Who is speaking" logic: the roomkey maintainers have the say here (review required)."""
from __future__ import annotations

FAMILY_TYPE = {"mama", "papa", "mami", "papi", "mutti", "vati", "oma", "opa", "omi", "opi", "tante", "onkel"}

# capitalised words that are never a name (sentence starts, pronouns, fillers)
STOP = {w.lower() for w in """Ich Sie Ihr Ihre Wir Es Er Hier Da Dort Jetzt Gleich Nicht Kein Keine Mal Nur Auch Schon Noch
    Zuhause Unten Oben Draußen Drinnen Ja Nein Okay Hallo Also Ah Äh Ähm Bitte Danke Moment Sorry Entschuldigung Leider Gerade
    Kurz Wieder Wer Was Wo Wie Warum Heute Morgen Gestern I You We They He She The This That Just Coming Here
    Und Aber Oder Dann Doch So Na Nun Das Die Der Den Dem Ein Eine Neue Neu Alles Nichts Etwas Viel Guten Gute Schön
    Mein Meine Dein Deine Unser Unsere Euer Eure Man Jemand Niemand Keiner Tschüss Servus Moin Grüß Wohnt Ist Sind
    Hast Habt Haben Kannst Könnt Können Kann Machst Macht Mach Komm Kommt Kommst Gib Geh Geht Soll Sollen Will Wollen
    Bin Bist War Waren Wird Werden Hat Hätte Würde Würden Gibt Liegt Steht Wartet Klingelt Schau Guck Sag Sagt
    Raus Rein Weg Los Hoch Runter Rauf Achtung Vorsicht Hilfe""".split()}
TITLES = {"frau", "herr", "herrn", "dr", "doktor", "prof", "schwester", "pfarrer", "pastor"}
# capitalised nouns that follow "ich bin" / "hier ist" without being a name ("ich bin Vegetarier", "hier ist Wasser")
NOT_NAMES = {w.lower() for w in """Montag Dienstag Mittwoch Donnerstag Freitag Samstag Sonntag Wochenende Feierabend
    Vegetarier Vegetarierin Veganer Veganerin Homeoffice Urlaub Arbeit Schule Uni Hause Keller Garten Küche Bad Dusche
    Toilette Klo Wasser Strom Licht Feuer Rauch Gas Chaos Ruhe Stress Mittag Mittagspause Abend Nacht Besuch Klingel Tür
    Haustür Treppe Treppenhaus Aufzug Wohnung Haus Auto Straße Bus Bahn Zug Weg Termin Meeting Telefon Handy Computer
    Essen Frühstück Kaffee Tee Geburtstag Party Feier Kind Baby Hund Katze Brief Rechnung Problem Notfall Fehler Unfall
    Einbruch Schluss Ende Anfang Glück Pech Spaß Ernst Sorge Angst Hunger Durst Fieber Krank Müde Fertig Allein Alleine
    Unterwegs Leute Menschen Männer Frauen Kinder Besucher Gast Gäste Bescheid Schuld Ordnung Platz Raum Zimmer Balkon
    Dach Hof Eingang Ausgang Stau Verspätung Pause Dienst Schicht Nachtschicht Spätschicht Frühschicht Training Sport
    Wetter Regen Schnee Sonne Winter Sommer Herbst Frühling Weihnachten Ostern Silvester Schnitt
    Schatz Schatzi Liebling Süße Süßer Mausi Hase Häschen Spatz Baby Darling Honey Meinung Ansicht Auffassung
    Überzeugung Hoffnung Ansicht Mieter Mieterin Vermieterin Eigentümer Eigentümerin Besitzer Kunde Kundin
    Nächste Nächster Erste Erster Letzte Letzter Einzige Einziger Richtige Falsche Pass Ausweis Schlüssel
    Deutscher Deutsche Türke Türkin Italiener Italienerin Spanier Spanierin Franzose Französin Pole Polin Russe Russin
    Ukrainer Ukrainerin Amerikaner Amerikanerin Kanadier Kanadierin Engländer Engländerin Brite Britin Österreicher
    Österreicherin Schweizer Schweizerin Grieche Griechin Rumäne Rumänin Syrer Syrerin Iraker Irakerin Afghane Afghanin
    Vietnamese Vietnamesin Chinese Chinesin Japaner Japanerin Inder Inderin Araber Araberin Kurde Kurdin
    Rentner Rentnerin Single""".split()}
# "ich bin (dein) Bruder / ein Freund von … / Student": not a name, but a fine self-description, shown as said
RELATION = {w.lower() for w in """Bruder Schwester Enkel Enkelin Sohn Tochter Cousin Cousine Neffe Nichte Schwager Schwägerin
    Schwiegersohn Schwiegertochter Patenkind Freund Freundin Kumpel Kollege Kollegin Mitbewohner Mitbewohnerin Student
    Studentin Schüler Schülerin Azubi Praktikant Praktikantin Vater Mutter Lieblingsnachbar Lieblingsnachbarin""".split()}
FAMILY_REL = {"bruder", "schwester", "enkel", "enkelin", "sohn", "tochter", "cousin", "cousine", "neffe", "nichte", "schwager",
              "schwägerin", "schwiegersohn", "schwiegertochter", "patenkind", "vater", "mutter"}
FAMILY = {"mama", "papa", "mami", "papi", "mutti", "vati", "oma", "opa", "omi", "opi", "tante", "onkel"}
