"""aikos app: the household's user interface in front of Home Assistant.

Home Assistant stays the system of record (entities, devices, states, events, sound and pictures). This service only holds
what Home Assistant cannot: accounts, passkeys, sessions, roles, push subscriptions and an audit log. It is the single
way from a phone to Home Assistant and enforces who may see and do what.
"""

__version__ = "0.5.0"
