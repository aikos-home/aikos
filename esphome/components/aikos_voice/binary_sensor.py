"""aikos_voice states: this end talks, in a call, a key has the floor (door), someone answered (door), busy (key).

The door sends `in_call` and `answered` to the room keys with packet_transport, so they must be binary sensors here.
"""

import esphome.codegen as cg
from esphome.components import binary_sensor
import esphome.config_validation as cv

from . import CONF_AIKOS_VOICE_ID, AikosVoice

DEPENDENCIES = ["aikos_voice"]

STATES = {
    "talking": ("set_talking_binary_sensor", "mdi:microphone"),
    "in_call": ("set_in_call_binary_sensor", "mdi:phone-in-talk"),
    "remote_holding": ("set_remote_holding_binary_sensor", "mdi:gesture-tap-hold"),
    "answered": ("set_answered_binary_sensor", "mdi:phone-check"),
    "busy": ("set_busy_binary_sensor", "mdi:phone-cancel"),
    "speech": ("set_speech_binary_sensor", "mdi:account-voice"),  # the speech detector hears speech at this mic now
}

CONFIG_SCHEMA = cv.Schema(
    {cv.GenerateID(CONF_AIKOS_VOICE_ID): cv.use_id(AikosVoice)}
    | {cv.Optional(key): binary_sensor.binary_sensor_schema(icon=icon) for key, (_, icon) in STATES.items()}
)


async def to_code(config):
    voice = await cg.get_variable(config[CONF_AIKOS_VOICE_ID])
    for key, (setter, _) in STATES.items():
        if key in config:
            b = await binary_sensor.new_binary_sensor(config[key])
            cg.add(getattr(voice, setter)(b))
