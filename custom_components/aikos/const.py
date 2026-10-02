"""Constants of the aikos integration."""
from datetime import time

DOMAIN = "aikos"
MANUFACTURER = "aikos-home"

# Settings, stored in the config entry's options.
OPT_QUIET_ENABLED = "quiet_hours_enabled"
OPT_QUIET_START = "quiet_hours_start"
OPT_QUIET_END = "quiet_hours_end"

# Requirement 1: the bell doesn't ring after about 8 pm.
DEFAULT_QUIET_ENABLED = True
DEFAULT_QUIET_START = time(20, 0)
DEFAULT_QUIET_END = time(7, 0)
