"""Is a parcel coming today (sprachausgabe S14/S15): the carriers' subjects as they really come (the items are made up),
followed per shipment; "delivered" ends it, the time window or the evening too; offers and "on its way" are no notice."""
from datetime import datetime, time

import pytest
from homeassistant.util import dt as dt_util

from custom_components.aikos.parcel_rules import DELIVERED, SOON, TODAY, classify, expectation


def at(hour, minute=0, day=21):
    return datetime(2026, 10, day, hour, minute, tzinfo=dt_util.get_default_time_zone())


@pytest.mark.parametrize("domain,subject,kind", [
    ("amazon.de", "In Zustellung: „Akku-Set 18650...\" und 2 weitere Artikel", TODAY),
    ("amazon.de", "Zugestellt: „Akku-Set 18650...“ und 2 weitere Artikel", DELIVERED),
    ("amazon.de", "Geliefert: \"Lötzinn 1 mm...“", DELIVERED),
    ("amazon.de", "Versendet: „Lötzinn 1 mm...“", None),
    ("amazon.de", "Stornierte Artikel: „Lötzinn 1 mm...“", None),
    ("amazon.de", "Heute: Angebote des Tages", None),
    ("dhl.de", "Ihre DHL Sendung kommt heute - Jetzt Live verfolgen...", TODAY),
    ("dhl.de", "Ihre Amazon Sendung kommt heute", TODAY),
    ("dhl.de", "Ihre  Versandhaus Sendung wird gleich zugestellt", SOON),
    ("dhl.de", "Ihre Sendung ist unterwegs und wird heute zugestellt", TODAY),
    ("dhl.de", "Ihre Sendung ist unterwegs", None),
    ("dhl.de", "Ihre Sendung liegt im Briefkasten", DELIVERED),
    ("dhl.de", "Ihre Sendung liegt am gewünschten Ablageort", DELIVERED),
    ("dhl.de", "Ihre Sendung wurde im Briefkasten zugestellt", DELIVERED),
    ("service.dpd.de", "Zwischen 13:45 und 15:45 Uhr kommt Ihr DPD Paket", TODAY),
    ("service.dpd.de", "Bald ist Ihr DPD Paket da", None),
    ("service.dpd.de", "Ihr Paket ist da!", DELIVERED),
    ("ups.com", "UPS Update: Paketzustellung heute", TODAY),
    ("ups.com", "Ihre UPS Lieferung wurde zugestellt", DELIVERED),
    ("gls-pakete.de", "Ihr GLS Paket kommt heute", TODAY),
    ("myhermes.de", "Ihre Hermes Sendung kommt voraussichtlich morgen", None),
    ("example.org", "Ihr Paket kommt heute", None),          # not a carrier: never read as a notice
])
def test_subjects(domain, subject, kind):
    n = classify(domain, subject, at(9))
    assert (n.kind if n else None) == kind


def test_amazon_follows_each_item_whatever_the_quotes():
    a = classify("amazon.de", "In Zustellung: „Akku-Set 18650...\" und 2 weitere Artikel", at(9))
    b = classify("amazon.de", "Zugestellt: „Akku-Set 18650...“ und 2 weitere Artikel", at(11))
    assert a.key == b.key == "amazon:akku-set 18650..."


def test_dpd_window():
    n = classify("service.dpd.de", "Zwischen 13:45 und 15:45 Uhr kommt Ihr DPD Paket", at(8))
    assert n.window == (time(13, 45), time(15, 45))


def notices(*items):
    return [classify(d, s, t) for d, s, t in items]


def test_expected_until_delivered():
    n = notices(("amazon.de", "In Zustellung: „Akku-Set...“", at(9)))
    assert expectation(n, at(10)).expected and expectation(n, at(10)).carriers == ("Amazon",)
    n += notices(("amazon.de", "Zugestellt: „Akku-Set...“", at(11)))
    assert not expectation(n, at(11, 5)).expected


def test_two_items_one_delivered_is_still_expected():
    n = notices(("amazon.de", "In Zustellung: „Akku-Set...“", at(9)), ("amazon.de", "In Zustellung: „Lötzinn...“", at(9, 1)),
                ("amazon.de", "Geliefert: „Lötzinn...“", at(10)))
    assert expectation(n, at(10, 5)).expected


def test_soon_and_the_window():
    n = notices(("dhl.de", "Ihre DHL Sendung kommt heute", at(8)), ("dhl.de", "Ihre Sendung wird gleich zugestellt", at(12)))
    e = expectation(n, at(12, 5))
    assert e.expected and e.soon
    n = notices(("service.dpd.de", "Zwischen 13:45 und 15:45 Uhr kommt Ihr DPD Paket", at(8)))
    assert expectation(n, at(14)).window == (time(13, 45), time(15, 45))
    assert expectation(n, at(16, 30)).expected                             # a little late is still expected
    assert not expectation(n, at(16, 46)).expected                         # window end + 1 h: over


def test_no_courier_after_the_evening_and_yesterday_is_over():
    n = notices(("dhl.de", "Ihre DHL Sendung kommt heute", at(8)))
    assert expectation(n, at(20, 59)).expected
    assert not expectation(n, at(21, 0)).expected
    n = notices(("dhl.de", "Ihre DHL Sendung kommt heute", at(8, day=20)))
    assert not expectation(n, at(9)).expected


def test_amazons_delivered_ends_the_carriers_notice_about_an_amazon_parcel():
    n = notices(("dhl.de", "Ihre Amazon Sendung kommt heute", at(8)), ("amazon.de", "Zugestellt: „Akku-Set...“", at(11)))
    assert not expectation(n, at(11, 5)).expected


def test_order_of_arrival_does_not_matter():
    n = notices(("amazon.de", "Zugestellt: „Akku-Set...“", at(11)), ("amazon.de", "In Zustellung: „Akku-Set...“", at(9)))
    assert not expectation(n, at(12)).expected
