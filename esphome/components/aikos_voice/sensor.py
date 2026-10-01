"""aikos_voice numbers: packet counters, and (door) the call id, the key that has the floor and the members.

The door sends `call_id` and `floor_key` to the room keys with packet_transport, so they must be sensors here.
"""

import esphome.codegen as cg
from esphome.components import sensor
import esphome.config_validation as cv
from esphome.const import ENTITY_CATEGORY_DIAGNOSTIC, STATE_CLASS_TOTAL_INCREASING

from . import CONF_AIKOS_VOICE_ID, AikosVoice

DEPENDENCIES = ["aikos_voice"]

COUNTERS = {
    "tx_packets": ("set_tx_packets_sensor", "mdi:upload-network"),
    "rx_packets": ("set_rx_packets_sensor", "mdi:download-network"),
    "held_back": ("set_held_back_sensor", "mdi:shield-lock-outline"),
    "tx_errors": ("set_tx_errors_sensor", "mdi:alert-circle-outline"),
}
CALL = {
    "call_id": ("set_call_id_sensor", "mdi:phone-log"),  # 24 bits, exact as a float
    "floor_key": ("set_floor_key_sensor", "mdi:account-voice"),  # last octet of the key that has the floor, 0 = none
    "members": ("set_members_sensor", "mdi:account-multiple"),
}
DIAG = {  # what the speech detector sees on this end's mic, once a second (dBFS after gain and high-pass)
    "speech_floor": ("set_speech_floor_sensor", "mdi:waveform"),  # the noise floor it compares with
    "speech_level": ("set_speech_level_sensor", "mdi:waveform"),  # the loudest block of the last second
}

CONFIG_SCHEMA = cv.Schema(
    {cv.GenerateID(CONF_AIKOS_VOICE_ID): cv.use_id(AikosVoice)}
    | {
        cv.Optional(key): sensor.sensor_schema(
            icon=icon,
            accuracy_decimals=0,
            state_class=STATE_CLASS_TOTAL_INCREASING,
            entity_category=ENTITY_CATEGORY_DIAGNOSTIC,
        )
        for key, (_, icon) in COUNTERS.items()
    }
    | {
        cv.Optional(key): sensor.sensor_schema(icon=icon, accuracy_decimals=0, entity_category=ENTITY_CATEGORY_DIAGNOSTIC)
        for key, (_, icon) in CALL.items()
    }
    | {
        cv.Optional(key): sensor.sensor_schema(
            icon=icon, unit_of_measurement="dBFS", accuracy_decimals=1, entity_category=ENTITY_CATEGORY_DIAGNOSTIC
        )
        for key, (_, icon) in DIAG.items()
    }
)


async def to_code(config):
    voice = await cg.get_variable(config[CONF_AIKOS_VOICE_ID])
    for key, (setter, _) in (COUNTERS | CALL | DIAG).items():
        if key in config:
            s = await sensor.new_sensor(config[key])
            cg.add(getattr(voice, setter)(s))
