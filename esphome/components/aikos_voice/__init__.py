"""aikos_voice: the shared voice link of the aikos door and room keys (voice v2, aikos features/sprechen.md R17).

  aikos_voice:
    id: voice
    role: door            # door: the arbiter of the call | room: one room key
    microphone: mic       # a microphone source (16 bit mono, 16 kHz)
    speaker: spk          # optional: where incoming audio is played
    transcriber: ""       # host:port for the copy of what this end says (also settable at runtime)
    door: ""              # room role: the door's host[:port] (also settable at runtime)
"""

import esphome.codegen as cg
from esphome import automation
from esphome.components import microphone, speaker
import esphome.config_validation as cv
from esphome.const import CONF_ID, CONF_MICROPHONE, CONF_PORT, CONF_SPEAKER

CODEOWNERS = ["@aikos-home"]
DEPENDENCIES = ["network", "microphone"]
MULTI_CONF = False

CONF_ROLE = "role"
CONF_TRANSCRIBER = "transcriber"
CONF_DOOR = "door"
CONF_PREBUFFER = "prebuffer"
CONF_LATCH_FRAMES = "latch_frames"
CONF_KEEPALIVE = "keepalive"
CONF_MIC_GAIN = "mic_gain"
CONF_HIGHPASS = "highpass"
CONF_MIC_START_MUTE = "mic_start_mute"
CONF_SILENCE_END = "silence_end"
CONF_MAX_LENGTH = "max_length"
CONF_MUTE_TAIL = "mute_tail"
CONF_HOLD_REFRESH = "hold_refresh"
CONF_RING_WINDOW = "ring_window"
CONF_HOST = "host"
CONF_HOSTS = "hosts"
CONF_ADDRESS = "address"
CONF_HELD = "held"
CONF_IN_CALL = "in_call"
CONF_ON = "on"
CONF_CALL_ID = "call_id"
CONF_ANSWERED = "answered"
CONF_KEY = "key"
CONF_DURATION = "duration"
CONF_GAIN = "gain"
CONF_VALUE = "value"
CONF_ON_TALK_START = "on_talk_start"
CONF_ON_TALK_STOP = "on_talk_stop"
CONF_ON_CALL_START = "on_call_start"
CONF_ON_CALL_END = "on_call_end"
CONF_AIKOS_VOICE_ID = "aikos_voice_id"

MS_OR_ZERO = cv.All(cv.time_period, cv.time_period_in_milliseconds_)  # 0 allowed (e.g. keepalive 0 = off)

aikos_voice_ns = cg.esphome_ns.namespace("aikos_voice")
AikosVoice = aikos_voice_ns.class_("AikosVoice", cg.Component)
VoiceRole = cg.global_ns.namespace("aikos").namespace("voice").enum("Role", is_class=True)
ROLES = {"door": VoiceRole.DOOR, "room": VoiceRole.ROOM}

RingAction = aikos_voice_ns.class_("RingAction", automation.Action)
VisitorSpeakAction = aikos_voice_ns.class_("VisitorSpeakAction", automation.Action)
JoinAction = aikos_voice_ns.class_("JoinAction", automation.Action)
EndAction = aikos_voice_ns.class_("EndAction", automation.Action)
SpeechDoorAction = aikos_voice_ns.class_("SpeechDoorAction", automation.Action)
SpeechRoomAction = aikos_voice_ns.class_("SpeechRoomAction", automation.Action)
KeyHoldAction = aikos_voice_ns.class_("KeyHoldAction", automation.Action)
KeyInCallAction = aikos_voice_ns.class_("KeyInCallAction", automation.Action)
HoldAction = aikos_voice_ns.class_("HoldAction", automation.Action)
DoorCallAction = aikos_voice_ns.class_("DoorCallAction", automation.Action)
FloorKeyAction = aikos_voice_ns.class_("FloorKeyAction", automation.Action)
StringAction = aikos_voice_ns.class_("StringAction", automation.Action)
BoolAction = aikos_voice_ns.class_("BoolAction", automation.Action)
AllowSourceAction = aikos_voice_ns.class_("AllowSourceAction", automation.Action)
SetMicGainAction = aikos_voice_ns.class_("SetMicGainAction", automation.Action)
SetDurationAction = aikos_voice_ns.class_("SetDurationAction", automation.Action)
IsTalkingCondition = aikos_voice_ns.class_("IsTalkingCondition", automation.Condition)
InCallCondition = aikos_voice_ns.class_("InCallCondition", automation.Condition)
RemoteHoldingCondition = aikos_voice_ns.class_("RemoteHoldingCondition", automation.Condition)

CONFIG_SCHEMA = cv.Schema(
    {
        cv.GenerateID(): cv.declare_id(AikosVoice),
        cv.Required(CONF_ROLE): cv.enum(ROLES, lower=True),
        cv.Required(CONF_MICROPHONE): microphone.microphone_source_schema(
            min_bits_per_sample=16, max_bits_per_sample=16, min_channels=1, max_channels=1
        ),
        cv.Optional(CONF_SPEAKER): cv.use_id(speaker.Speaker),
        cv.Optional(CONF_PORT, default=5004): cv.port,
        cv.Optional(CONF_TRANSCRIBER, default=""): cv.string,
        cv.Optional(CONF_DOOR, default=""): cv.string,
        cv.Optional(CONF_PREBUFFER, default="300ms"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_LATCH_FRAMES, default=3): cv.int_range(0, 10),
        cv.Optional(CONF_KEEPALIVE, default="60s"): MS_OR_ZERO,
        cv.Optional(CONF_MIC_GAIN, default=4.0): cv.float_range(0.1, 64.0),
        cv.Optional(CONF_HIGHPASS, default=True): cv.boolean,
        cv.Optional(CONF_MIC_START_MUTE, default="0ms"): MS_OR_ZERO,
        cv.Optional(CONF_SILENCE_END, default="10s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_MAX_LENGTH, default="300s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_MUTE_TAIL, default="300ms"): MS_OR_ZERO,
        cv.Optional(CONF_HOLD_REFRESH, default="3s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_RING_WINDOW, default="120s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_ON_TALK_START): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_TALK_STOP): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_CALL_START): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_CALL_END): automation.validate_automation(single=True),
    }
).extend(cv.COMPONENT_SCHEMA)

FINAL_VALIDATE_SCHEMA = cv.Schema(
    {
        cv.Required(CONF_MICROPHONE): microphone.final_validate_microphone_source_schema(
            "aikos_voice", sample_rate=16000
        ),
    },
    extra=cv.ALLOW_EXTRA,
)


async def to_code(config):
    var = cg.new_Pvariable(config[CONF_ID])
    await cg.register_component(var, config)
    mic_source = await microphone.microphone_source_to_code(config[CONF_MICROPHONE])
    cg.add(var.set_microphone_source(mic_source))
    if CONF_SPEAKER in config:
        spk = await cg.get_variable(config[CONF_SPEAKER])
        cg.add(var.set_speaker(spk))
    cg.add(var.set_role(config[CONF_ROLE]))
    cg.add(var.set_port(config[CONF_PORT]))
    cg.add(var.set_initial_transcriber(config[CONF_TRANSCRIBER]))
    cg.add(var.set_initial_door(config[CONF_DOOR]))
    cg.add(var.set_prebuffer(config[CONF_PREBUFFER]))
    cg.add(var.set_latch_frames(config[CONF_LATCH_FRAMES]))
    cg.add(var.set_keepalive(config[CONF_KEEPALIVE]))
    cg.add(var.set_mic_gain(config[CONF_MIC_GAIN]))
    cg.add(var.set_highpass(config[CONF_HIGHPASS]))
    cg.add(var.set_mic_start_mute(config[CONF_MIC_START_MUTE]))
    cg.add(var.set_silence_end(config[CONF_SILENCE_END]))
    cg.add(var.set_max_length(config[CONF_MAX_LENGTH]))
    cg.add(var.set_mute_tail(config[CONF_MUTE_TAIL]))
    cg.add(var.set_hold_refresh(config[CONF_HOLD_REFRESH]))
    cg.add(var.set_ring_window(config[CONF_RING_WINDOW]))
    for conf_key, getter in (
        (CONF_ON_TALK_START, var.get_talk_start_trigger()),
        (CONF_ON_TALK_STOP, var.get_talk_stop_trigger()),
        (CONF_ON_CALL_START, var.get_call_start_trigger()),
    ):
        if conf_key in config:
            await automation.build_automation(getter, [], config[conf_key])
    if CONF_ON_CALL_END in config:  # with the reason: "silence", "max length", "door unreachable", ...
        await automation.build_automation(
            var.get_call_end_trigger(), [(cg.std_string, "reason")], config[CONF_ON_CALL_END]
        )


VOICE_ACTION_SCHEMA = automation.maybe_simple_id({cv.GenerateID(): cv.use_id(AikosVoice)})


async def _parented(config, action_id, template_arg):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var


@automation.register_action("aikos_voice.ring", RingAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.visitor_speak", VisitorSpeakAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.join", JoinAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.end", EndAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.speech_door", SpeechDoorAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.speech_room", SpeechRoomAction, VOICE_ACTION_SCHEMA, synchronous=True)
async def voice_simple_action(config, action_id, template_arg, args):
    return await _parented(config, action_id, template_arg)


def _key_schema(flag):
    return cv.Schema(
        {
            cv.GenerateID(): cv.use_id(AikosVoice),
            cv.Required(CONF_HOST): cv.templatable(cv.string),
            cv.Required(flag): cv.templatable(cv.boolean),
        }
    )


@automation.register_action("aikos_voice.key_hold", KeyHoldAction, _key_schema(CONF_HELD), synchronous=True)
async def key_hold_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_host(await cg.templatable(config[CONF_HOST], args, cg.std_string)))
    cg.add(var.set_held(await cg.templatable(config[CONF_HELD], args, cg.bool_)))
    return var


@automation.register_action("aikos_voice.key_in_call", KeyInCallAction, _key_schema(CONF_IN_CALL), synchronous=True)
async def key_in_call_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_host(await cg.templatable(config[CONF_HOST], args, cg.std_string)))
    cg.add(var.set_in_call(await cg.templatable(config[CONF_IN_CALL], args, cg.bool_)))
    return var


@automation.register_action(
    "aikos_voice.hold",
    HoldAction,
    cv.maybe_simple_value(
        {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_HELD): cv.templatable(cv.boolean)}, key=CONF_HELD
    ),
    synchronous=True,
)
async def hold_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_held(await cg.templatable(config[CONF_HELD], args, cg.bool_)))
    return var


@automation.register_action(
    "aikos_voice.door_call",
    DoorCallAction,
    cv.Schema(
        {
            cv.GenerateID(): cv.use_id(AikosVoice),
            cv.Required(CONF_ON): cv.templatable(cv.boolean),
            cv.Required(CONF_CALL_ID): cv.templatable(cv.uint32_t),
            cv.Required(CONF_ANSWERED): cv.templatable(cv.boolean),
        }
    ),
    synchronous=True,
)
async def door_call_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_on(await cg.templatable(config[CONF_ON], args, cg.bool_)))
    cg.add(var.set_call_id(await cg.templatable(config[CONF_CALL_ID], args, cg.uint32)))
    cg.add(var.set_answered(await cg.templatable(config[CONF_ANSWERED], args, cg.bool_)))
    return var


@automation.register_action(
    "aikos_voice.floor_key",
    FloorKeyAction,
    cv.maybe_simple_value(
        {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_KEY): cv.templatable(cv.int_range(0, 255))},
        key=CONF_KEY,
    ),
    synchronous=True,
)
async def floor_key_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_key(await cg.templatable(config[CONF_KEY], args, cg.int_)))
    return var


# actions that pass one string or one bool to a setter
STRING_ACTIONS = {
    "aikos_voice.set_transcriber": "set_transcriber",
    "aikos_voice.set_keys": "set_keys",
    "aikos_voice.set_door": "set_door",
}
BOOL_ACTIONS = {
    "aikos_voice.hear_visitor": "set_hear_visitor",
    "aikos_voice.record": "record",
}


def _register_string(name, setter):
    @automation.register_action(
        name,
        StringAction,
        cv.maybe_simple_value(
            {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_VALUE): cv.templatable(cv.string)},
            key=CONF_VALUE,
        ),
        synchronous=True,
    )
    async def _action(config, action_id, template_arg, args):
        var = await _parented(config, action_id, template_arg)
        cg.add(var.set_value(await cg.templatable(config[CONF_VALUE], args, cg.std_string)))
        cg.add(var.set_setter(cg.RawExpression(f"&esphome::aikos_voice::AikosVoice::{setter}")))
        return var


def _register_bool(name, setter):
    @automation.register_action(
        name,
        BoolAction,
        cv.maybe_simple_value(
            {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_VALUE): cv.templatable(cv.boolean)},
            key=CONF_VALUE,
        ),
        synchronous=True,
    )
    async def _action(config, action_id, template_arg, args):
        var = await _parented(config, action_id, template_arg)
        cg.add(var.set_value(await cg.templatable(config[CONF_VALUE], args, cg.bool_)))
        cg.add(var.set_setter(cg.RawExpression(f"&esphome::aikos_voice::AikosVoice::{setter}")))
        return var


for _name, _setter in STRING_ACTIONS.items():
    _register_string(_name, _setter)
for _name, _setter in BOOL_ACTIONS.items():
    _register_bool(_name, _setter)

DURATION_ACTIONS = {
    "aikos_voice.set_silence_end": "set_call_silence_end",
    "aikos_voice.set_max_length": "set_call_max_length",
}


def _register_duration(name, setter):
    @automation.register_action(
        name,
        SetDurationAction,
        cv.maybe_simple_value(
            {
                cv.GenerateID(): cv.use_id(AikosVoice),
                cv.Required(CONF_VALUE): cv.templatable(cv.positive_time_period_milliseconds),
            },
            key=CONF_VALUE,
        ),
        synchronous=True,
    )
    async def _action(config, action_id, template_arg, args):
        var = await _parented(config, action_id, template_arg)
        cg.add(var.set_value(await cg.templatable(config[CONF_VALUE], args, cg.uint32)))
        cg.add(var.set_setter(cg.RawExpression(f"&esphome::aikos_voice::AikosVoice::{setter}")))
        return var


for _name, _setter in DURATION_ACTIONS.items():
    _register_duration(_name, _setter)


@automation.register_action(
    "aikos_voice.allow_source",
    AllowSourceAction,
    cv.Schema(
        {
            cv.GenerateID(): cv.use_id(AikosVoice),
            cv.Required(CONF_HOST): cv.templatable(cv.string),
            cv.Required(CONF_DURATION): cv.templatable(cv.positive_time_period_milliseconds),
        }
    ),
    synchronous=True,
)
async def allow_source_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_host(await cg.templatable(config[CONF_HOST], args, cg.std_string)))
    cg.add(var.set_duration(await cg.templatable(config[CONF_DURATION], args, cg.uint32)))
    return var


@automation.register_action(
    "aikos_voice.set_mic_gain",
    SetMicGainAction,
    cv.maybe_simple_value(
        {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_GAIN): cv.templatable(cv.float_range(0.1, 64.0))},
        key=CONF_GAIN,
    ),
    synchronous=True,
)
async def set_mic_gain_action(config, action_id, template_arg, args):
    var = await _parented(config, action_id, template_arg)
    cg.add(var.set_gain(await cg.templatable(config[CONF_GAIN], args, cg.float_)))
    return var


@automation.register_condition("aikos_voice.is_talking", IsTalkingCondition, VOICE_ACTION_SCHEMA)
@automation.register_condition("aikos_voice.in_call", InCallCondition, VOICE_ACTION_SCHEMA)
@automation.register_condition("aikos_voice.remote_holding", RemoteHoldingCondition, VOICE_ACTION_SCHEMA)
async def voice_condition(config, condition_id, template_arg, args):
    var = cg.new_Pvariable(condition_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var
