"""Constants of the aikos integration."""
from datetime import time

DOMAIN = "aikos"
MANUFACTURER = "aikos-home"

# Settings, stored in the config entry's options.
OPT_QUIET_ENABLED = "quiet_hours_enabled"
OPT_QUIET_START = "quiet_hours_start"
OPT_QUIET_END = "quiet_hours_end"

# Ring push (options flow): which entity is the doorbell, who lives here, where pushes go.
OPT_DOORBELL = "doorbell"
OPT_RESIDENTS = "residents"
OPT_NOTIFY = "notify_targets"
# Call archive (R23, developer use): every call as JSON lines in <config>/aikos_archive/calls.jsonl. Default off.
OPT_ARCHIVE = "call_archive"
# The front door contact the devices follow (binary_sensor.aikos_front_door, debounced).
OPT_FRONT_DOOR = "front_door"
# The TTS service that reads notes and greetings aloud in the residents' own voices (aikos-app A42–A45; a local one,
# e.g. the aikos TTS service through the Wyoming integration). Empty = text is only shown.
OPT_TTS = "tts_engine"

# Call log sources. Live: the transcriber's sensors and the talk computer's call sensor (ids as the devices and the
# transcriber create them). Test: the bench stand-ins from the homeassistant/ package, so tests never touch the live log.
LIVE_TRANSCRIPT_ROOM = "sensor.talk_transcript"
LIVE_TRANSCRIPT_DOOR = "sensor.talk_transcript_door"
LIVE_CALL = "binary_sensor.aikos_intercom_talk_in_call"
TEST_TRANSCRIPT_ROOM = "sensor.talk_transcript_test"
TEST_TRANSCRIPT_DOOR = "sensor.talk_transcript_door_test"
TEST_CALL = "input_boolean.aikos_test_in_call"
TEST_NEW_CALL = "input_button.aikos_test_new_call"

# Door message register (aikos-app A10, A15): the door's contracts. The screen names the recipient when a recording starts
# (screen 0.7.18), the talk computer reports the recording (0.7.23), the recorder saves the MP3 into Home Assistant's local
# media folder below and tells it with an event. The door transcripts are LIVE_TRANSCRIPT_DOOR.
DOOR_RECIPIENT_EVENT = "esphome.aikos_door_message"
DOOR_MESSAGE_RECORDING = "binary_sensor.aikos_intercom_talk_message_recording"
DOOR_SAVED_EVENT = "aikos_door_message_saved"
DOOR_FAILED_EVENT = "aikos_door_message_failed"
DOOR_MEDIA_FOLDER = "aikos_door"

# Door actions (aikos-app A11–A14, A39–A41): the screen's contracts (vertraege.md, screen 0.7.18–0.7.20).
DOOR_SOMEONE = "binary_sensor.aikos_intercom_screen_someone_at_the_door"
DOOR_GREETING_TEXT = "text.aikos_intercom_screen_greeting"
DOOR_PHOTO_URL = "text.aikos_intercom_screen_photo_url"
DOOR_SHOW_REPLY = "aikos_intercom_screen_show_reply"   # ESPHome action of the screen

# Requirement 1: the bell doesn't ring after about 8 pm.
DEFAULT_QUIET_ENABLED = True
DEFAULT_QUIET_START = time(20, 0)
DEFAULT_QUIET_END = time(7, 0)
