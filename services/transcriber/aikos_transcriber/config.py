"""Configuration of one transcriber side, from the environment (launchd: EnvironmentVariables).

    AIKOS_SIDE          room | door                                          (required)
    AIKOS_PORT          default 5006 (room) / 5008 (door)
    AIKOS_HA_URL        Home Assistant base URL                              (required)
    AIKOS_HA_TOKEN_FILE file with a long-lived HA token, mode 600            (required, must be readable)
    AIKOS_KNOWN_NAMES   household first names, comma-separated (improves Whisper and the display)
    AIKOS_WHISPER_URL   default http://127.0.0.1:6667/v1/audio/transcriptions
    AIKOS_LLM_URL       default http://127.0.0.1:11434   (Ollama; model qwen3:8b, kept loaded)
    AIKOS_RECORDINGS    default ~/Library/Application Support/aikos/transcriber/recordings
    AIKOS_PYTHON        python for the worker; default: the one running the receiver
    AIKOS_LIVE          1 = publish partial text while talking; default 1 for the door side, 0 for the room side
    AIKOS_STATE_DIR     default ~/Library/Application Support/aikos/transcriber (shared by both sides: "a resident talks")
    AIKOS_TEST_SOURCES  comma-separated IPs of test senders; unset = 127.0.0.1, empty = none. Their text goes to *_test entities.
    AIKOS_SPLIT         door side: 1 = cut the door audio into utterances at pauses (voice v2, mic on for the whole call); default 0
    AIKOS_VISITOR_TRANSLATION  room side: 1 = translate the resident's answer into the visitor's language (R28); default 0

Same names and defaults as roomkey tools/transcriber_service.sh at d0d52b9.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SUPPORT = Path("~/Library/Application Support/aikos/transcriber").expanduser()


class ConfigError(Exception):
    pass


@dataclass
class Config:
    side: str
    port: int
    ha_url: str
    token_file: Path
    known_names: str = ""
    whisper_url: str = "http://127.0.0.1:6667/v1/audio/transcriptions"
    llm_url: str = "http://127.0.0.1:11434"
    recordings: Path = SUPPORT / "recordings"
    python: str = ""
    live: bool = False
    state_dir: Path = SUPPORT
    test_sources: str = "127.0.0.1"
    split: bool = False
    visitor_translation: bool = False

    @property
    def activity_file(self) -> Path:
        """Touched by the room side while a resident talks; read by the door side (echo guard, live quiet)."""
        return self.state_dir / "room_active"

    @property
    def live_entity(self) -> str:
        return "sensor.talk_live_door" if self.side == "door" else "sensor.talk_live"

    @classmethod
    def from_env(cls, env) -> "Config":
        side = env.get("AIKOS_SIDE", "")
        if side not in ("room", "door"):
            raise ConfigError("AIKOS_SIDE=room|door")
        ha_url = env.get("AIKOS_HA_URL", "")
        if not ha_url:
            raise ConfigError("AIKOS_HA_URL is required")
        token = env.get("AIKOS_HA_TOKEN_FILE", "")
        if not token:
            raise ConfigError("AIKOS_HA_TOKEN_FILE is required")
        token_file = Path(token)
        try:
            token_file.open().close()
        except OSError:
            raise ConfigError(f"token file not readable: {token}")
        return cls(
            side=side,
            port=int(env.get("AIKOS_PORT") or (5006 if side == "room" else 5008)),
            ha_url=ha_url,
            token_file=token_file,
            known_names=env.get("AIKOS_KNOWN_NAMES", ""),
            whisper_url=env.get("AIKOS_WHISPER_URL") or cls.whisper_url,
            llm_url=env.get("AIKOS_LLM_URL") or cls.llm_url,
            recordings=Path(env["AIKOS_RECORDINGS"]) if env.get("AIKOS_RECORDINGS") else SUPPORT / "recordings",
            python=env.get("AIKOS_PYTHON", ""),
            live=(env.get("AIKOS_LIVE") or ("1" if side == "door" else "0")) == "1",
            state_dir=Path(env["AIKOS_STATE_DIR"]) if env.get("AIKOS_STATE_DIR") else SUPPORT,
            test_sources=env.get("AIKOS_TEST_SOURCES", "127.0.0.1"),
            split=env.get("AIKOS_SPLIT", "0") == "1",
            visitor_translation=env.get("AIKOS_VISITOR_TRANSLATION", "0") == "1",
        )
