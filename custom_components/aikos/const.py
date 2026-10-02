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

# Requirement 1: the bell doesn't ring after about 8 pm.
DEFAULT_QUIET_ENABLED = True
DEFAULT_QUIET_START = time(20, 0)
DEFAULT_QUIET_END = time(7, 0)
