"""aikos_voice: the shared voice link of the aikos door and RoomKeys (voice v1, aikos vertraege.md §4).

  aikos_voice:
    id: voice
    role: door            # door: play a key only while it holds | room: play the door during a conversation
    microphone: mic       # a microphone source (16 bit mono)
    speaker: spk          # optional: where incoming audio is played
    transcriber: ""       # host:port for the copy of what this end says (also settable at runtime)
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
CONF_IDLE_TIMEOUT = "idle_timeout"
CONF_PREBUFFER = "prebuffer"
CONF_HOLD_MAX = "hold_max"
CONF_LATCH_FRAMES = "latch_frames"
CONF_KEEPALIVE = "keepalive"
CONF_MIC_GAIN = "mic_gain"
CONF_HIGHPASS = "highpass"
CONF_HELD = "held"
CONF_PEER_HOST = "peer_host"
CONF_HOST = "host"
CONF_ADDRESS = "address"
CONF_ACCEPT = "accept"
CONF_DURATION = "duration"
CONF_GAIN = "gain"
CONF_ON_TALK_START = "on_talk_start"
CONF_ON_TALK_STOP = "on_talk_stop"
CONF_ON_CONVERSATION_START = "on_conversation_start"
CONF_ON_CONVERSATION_END = "on_conversation_end"
CONF_AIKOS_VOICE_ID = "aikos_voice_id"

aikos_voice_ns = cg.esphome_ns.namespace("aikos_voice")
AikosVoice = aikos_voice_ns.class_("AikosVoice", cg.Component)
VoiceRole = cg.global_ns.namespace("aikos").namespace("voice").enum("Role", is_class=True)
ROLES = {"door": VoiceRole.DOOR, "room": VoiceRole.ROOM}

TalkStartAction = aikos_voice_ns.class_("TalkStartAction", automation.Action)
TalkStopAction = aikos_voice_ns.class_("TalkStopAction", automation.Action)
RemoteHoldAction = aikos_voice_ns.class_("RemoteHoldAction", automation.Action)
SetPeerAction = aikos_voice_ns.class_("SetPeerAction", automation.Action)
EndAction = aikos_voice_ns.class_("EndAction", automation.Action)
SetTranscriberAction = aikos_voice_ns.class_("SetTranscriberAction", automation.Action)
SetAcceptAction = aikos_voice_ns.class_("SetAcceptAction", automation.Action)
AllowSourceAction = aikos_voice_ns.class_("AllowSourceAction", automation.Action)
SetMicGainAction = aikos_voice_ns.class_("SetMicGainAction", automation.Action)
IsTalkingCondition = aikos_voice_ns.class_("IsTalkingCondition", automation.Condition)
InConversationCondition = aikos_voice_ns.class_("InConversationCondition", automation.Condition)
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
        cv.Optional(CONF_IDLE_TIMEOUT, default="120s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_PREBUFFER, default="300ms"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_HOLD_MAX, default="90s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_LATCH_FRAMES, default=3): cv.int_range(0, 10),
        cv.Optional(CONF_KEEPALIVE, default="60s"): cv.positive_time_period_milliseconds,
        cv.Optional(CONF_MIC_GAIN, default=4.0): cv.float_range(0.1, 64.0),
        cv.Optional(CONF_HIGHPASS, default=True): cv.boolean,
        cv.Optional(CONF_ON_TALK_START): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_TALK_STOP): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_CONVERSATION_START): automation.validate_automation(single=True),
        cv.Optional(CONF_ON_CONVERSATION_END): automation.validate_automation(single=True),
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
    cg.add(var.set_idle_timeout(config[CONF_IDLE_TIMEOUT]))
    cg.add(var.set_prebuffer(config[CONF_PREBUFFER]))
    cg.add(var.set_hold_max(config[CONF_HOLD_MAX]))
    cg.add(var.set_latch_frames(config[CONF_LATCH_FRAMES]))
    cg.add(var.set_keepalive(config[CONF_KEEPALIVE]))
    cg.add(var.set_mic_gain(config[CONF_MIC_GAIN]))
    cg.add(var.set_highpass(config[CONF_HIGHPASS]))
    for conf_key, getter in (
        (CONF_ON_TALK_START, var.get_talk_start_trigger()),
        (CONF_ON_TALK_STOP, var.get_talk_stop_trigger()),
        (CONF_ON_CONVERSATION_START, var.get_conversation_start_trigger()),
        (CONF_ON_CONVERSATION_END, var.get_conversation_end_trigger()),
    ):
        if conf_key in config:
            await automation.build_automation(getter, [], config[conf_key])


VOICE_ACTION_SCHEMA = automation.maybe_simple_id({cv.GenerateID(): cv.use_id(AikosVoice)})


@automation.register_action("aikos_voice.talk_start", TalkStartAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.talk_stop", TalkStopAction, VOICE_ACTION_SCHEMA, synchronous=True)
@automation.register_action("aikos_voice.end", EndAction, VOICE_ACTION_SCHEMA, synchronous=True)
async def voice_simple_action(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var


@automation.register_action(
    "aikos_voice.remote_hold",
    RemoteHoldAction,
    cv.Schema(
        {
            cv.GenerateID(): cv.use_id(AikosVoice),
            cv.Required(CONF_HELD): cv.templatable(cv.boolean),
            cv.Optional(CONF_PEER_HOST, default=""): cv.templatable(cv.string),
        }
    ),
    synchronous=True,
)
async def remote_hold_action(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    cg.add(var.set_held(await cg.templatable(config[CONF_HELD], args, cg.bool_)))
    cg.add(var.set_peer_host(await cg.templatable(config[CONF_PEER_HOST], args, cg.std_string)))
    return var


@automation.register_action(
    "aikos_voice.set_peer",
    SetPeerAction,
    cv.Schema(
        {
            cv.GenerateID(): cv.use_id(AikosVoice),
            cv.Required(CONF_HOST): cv.templatable(cv.string),
            cv.Optional(CONF_PORT, default=5004): cv.templatable(cv.port),
        }
    ),
    synchronous=True,
)
async def set_peer_action(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    cg.add(var.set_host(await cg.templatable(config[CONF_HOST], args, cg.std_string)))
    cg.add(var.set_port(await cg.templatable(config[CONF_PORT], args, cg.int_)))
    return var


@automation.register_action(
    "aikos_voice.set_transcriber",
    SetTranscriberAction,
    cv.maybe_simple_value(
        {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_ADDRESS): cv.templatable(cv.string)},
        key=CONF_ADDRESS,
    ),
    synchronous=True,
)
async def set_transcriber_action(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    cg.add(var.set_address(await cg.templatable(config[CONF_ADDRESS], args, cg.std_string)))
    return var


@automation.register_action(
    "aikos_voice.set_accept",
    SetAcceptAction,
    cv.maybe_simple_value(
        {cv.GenerateID(): cv.use_id(AikosVoice), cv.Required(CONF_ACCEPT): cv.templatable(cv.boolean)},
        key=CONF_ACCEPT,
    ),
    synchronous=True,
)
async def set_accept_action(config, action_id, template_arg, args):
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    cg.add(var.set_accept(await cg.templatable(config[CONF_ACCEPT], args, cg.bool_)))
    return var


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
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
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
    var = cg.new_Pvariable(action_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    cg.add(var.set_gain(await cg.templatable(config[CONF_GAIN], args, cg.float_)))
    return var


@automation.register_condition("aikos_voice.is_talking", IsTalkingCondition, VOICE_ACTION_SCHEMA)
@automation.register_condition("aikos_voice.in_conversation", InConversationCondition, VOICE_ACTION_SCHEMA)
@automation.register_condition("aikos_voice.remote_holding", RemoteHoldingCondition, VOICE_ACTION_SCHEMA)
async def voice_condition(config, condition_id, template_arg, args):
    var = cg.new_Pvariable(condition_id, template_arg)
    await cg.register_parented(var, config[CONF_ID])
    return var
