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

# Call log sources. Live: the transcriber's sensors and the talk computer's call sensor (ids as the devices and the
# transcriber create them). Test: the bench stand-ins from the homeassistant/ package, so tests never touch the live log.
LIVE_TRANSCRIPT_ROOM = "sensor.talk_transcript"
LIVE_TRANSCRIPT_DOOR = "sensor.talk_transcript_door"
LIVE_CALL = "binary_sensor.aikos_intercom_talk_in_call"
TEST_TRANSCRIPT_ROOM = "sensor.talk_transcript_test"
TEST_TRANSCRIPT_DOOR = "sensor.talk_transcript_door_test"
TEST_CALL = "input_boolean.aikos_test_in_call"
TEST_NEW_CALL = "input_button.aikos_test_new_call"

# Requirement 1: the bell doesn't ring after about 8 pm.
DEFAULT_QUIET_ENABLED = True
DEFAULT_QUIET_START = time(20, 0)
DEFAULT_QUIET_END = time(7, 0)
