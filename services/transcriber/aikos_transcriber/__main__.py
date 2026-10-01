"""Run one receiver side of the aikos transcriber (replaces roomkey tools/transcriber_service.sh at d0d52b9, same behaviour).

    python -m aikos_transcriber            # configuration from the environment, see config.py

Side "room": RoomKeys → UDP 5006 → sensor.talk_transcript (shown at the door).
Side "door": door     → UDP 5008 → sensor.talk_transcript_door (shown on the keys).
Every utterance is handed to `python -m aikos_transcriber.worker` in its own process. If the port is taken (another receiver
still runs), the receiver exits and launchd starts it again.
"""
from __future__ import annotations

import os
import shlex
import sys
from pathlib import Path

from . import receiver
from .config import Config, ConfigError


def receiver_args(c: Config, python: str) -> list[str]:
    """The receiver's command line, exactly as transcriber_service.sh built it."""
    q = shlex.quote
    extra: list[str] = []
    if c.live:
        extra += ["--live", c.live_entity, "--live-side", c.side, "--ha-url", c.ha_url, "--token-file", str(c.token_file),
                  "--whisper-url", c.whisper_url, "--known-names", c.known_names]
    echo_args = ""
    if c.side == "room":
        extra += ["--activity-file", str(c.activity_file)]                # "a resident talks" (for the door side's echo guard)
    else:
        if c.split:                                                       # voice v2: door mic on for the whole call
            extra += ["--split-on-silence"]
        extra += ["--live-quiet-file", str(c.activity_file)]
        echo_args = f"--activity-file {q(str(c.activity_file))}"
    worker = (f"{q(python)} -u -m aikos_transcriber.worker {{wav}} --side {c.side} --source-ip {{src}} --ha-url {q(c.ha_url)} "
              f"--token-file {q(str(c.token_file))} --whisper-url {q(c.whisper_url)} --llm-url {q(c.llm_url)} "
              f"--known-names {q(c.known_names)} --delete-wav --test-sources {q(c.test_sources)} {echo_args}").rstrip()
    warm_llm = f"curl -s -m 30 {q(c.llm_url)}/api/generate -d '{{\"model\":\"qwen3:8b\",\"keep_alive\":-1}}' >/dev/null"
    return (["--port", str(c.port), "--out", str(c.recordings), "--test-sources", c.test_sources] + extra
            + ["--on-start", warm_llm, "--exec", worker])


def main() -> None:
    try:
        c = Config.from_env(os.environ)
    except ConfigError as exc:
        print(exc, file=sys.stderr)
        sys.exit(2)
    os.chdir(Path(__file__).resolve().parent.parent)                     # the worker is started as `-m aikos_transcriber.worker`
    c.recordings.mkdir(parents=True, exist_ok=True)
    c.state_dir.mkdir(parents=True, exist_ok=True)
    receiver.main(receiver_args(c, c.python or sys.executable))


if __name__ == "__main__":
    main()
