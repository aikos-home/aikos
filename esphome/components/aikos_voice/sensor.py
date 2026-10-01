"""aikos_voice counters: packets sent, received (played), held back (never played), errors."""

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
)


async def to_code(config):
    voice = await cg.get_variable(config[CONF_AIKOS_VOICE_ID])
    for key, (setter, _) in COUNTERS.items():
        if key in config:
            s = await sensor.new_sensor(config[key])
            cg.add(getattr(voice, setter)(s))
