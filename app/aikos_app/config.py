"""Settings from the environment. Nothing here knows a particular house; every house value comes from outside."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SUPERVISOR_URL = "http://supervisor/core"


@dataclass(frozen=True)
class Settings:
    public_url: str
    """The address phones open, e.g. https://app.example.org. Its host is the passkey relying party (RP ID)."""
    listen_host: str = "127.0.0.1"
    port: int = 8780
    trust_proxy: bool = False
    """Behind the reverse proxy: take the client address from X-Forwarded-For (for the brake and the audit log)."""
    data_dir: Path = Path("data")
    db_url: str = ""
    """Empty = SQLite file in the data folder. `rqlites://a:4001,b:4001,c:4001` = rqlite cluster over HTTPS."""
    db_user: str = ""
    db_password: str = field(default="", repr=False)
    db_ca_file: str = ""
    commit: str = ""
    """The git commit this build came from (baked into the image); the rollout checks it after an update."""
    rp_name: str = "aikos"
    ha_url: str = ""
    ha_token: str = field(default="", repr=False)
    web_dir: Path | None = None
    assetlinks_file: Path | None = None
    door_media_dir: str = "aikos_door"
    """Folder below Home Assistant's local media that holds the door's messages and drawings."""
    entity_someone_at_door: str = "binary_sensor.aikos_intercom_screen_someone_at_the_door"
    entity_quiet_hours: str = "binary_sensor.aikos_quiet_hours"
    entity_bell_muted: str = "binary_sensor.aikos_bell_muted"
    interim_last_message_entity: str = ""
    """Interim source (until the aikos integration keeps the message register): an entity whose state is the file name of
    the last saved message with attributes seconds, time, recipient. Empty = off."""
    interim_message_text_entity: str = ""
    """Interim source: an entity whose state is the recognised text of the message being recorded. Empty = off."""

    @property
    def origin(self) -> str:
        parts = urlsplit(self.public_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def rp_id(self) -> str:
        return urlsplit(self.public_url).hostname or "localhost"

    @property
    def secure_context(self) -> bool:
        """Passkeys only work over HTTPS, or on localhost."""
        parts = urlsplit(self.public_url)
        return parts.scheme == "https" or parts.hostname in ("localhost", "127.0.0.1")


def _read_secret(path: str) -> str:
    return Path(path).read_text(encoding="utf-8").strip() if path else ""


def from_env(env: dict[str, str] | None = None) -> Settings:
    e = os.environ if env is None else env
    port = int(e.get("AIKOS_APP_PORT", "8780"))
    supervisor_token = e.get("SUPERVISOR_TOKEN", "")
    ha_url = e.get("AIKOS_APP_HA_URL", SUPERVISOR_URL if supervisor_token else "")
    ha_token = _read_secret(e.get("AIKOS_APP_HA_TOKEN_FILE", "")) or supervisor_token
    web_dir = e.get("AIKOS_APP_WEB_DIR", "")
    assetlinks = e.get("AIKOS_APP_ASSETLINKS_FILE", "")
    defaults = Settings(public_url="")
    return Settings(
        public_url=e.get("AIKOS_APP_PUBLIC_URL", f"http://localhost:{port}").rstrip("/"),
        listen_host=e.get("AIKOS_APP_LISTEN", "127.0.0.1"),
        port=port,
        trust_proxy=e.get("AIKOS_APP_TRUST_PROXY", "") in ("1", "true", "yes"),
        data_dir=Path(e.get("AIKOS_APP_DATA_DIR", "data")),
        db_url=e.get("AIKOS_APP_DB", ""),
        db_user=e.get("AIKOS_APP_DB_USER", ""),
        db_password=_read_secret(e.get("AIKOS_APP_DB_PASSWORD_FILE", "")),
        db_ca_file=e.get("AIKOS_APP_DB_CA_FILE", ""),
        commit=e.get("AIKOS_APP_COMMIT", ""),
        rp_name=e.get("AIKOS_APP_RP_NAME", "aikos"),
        ha_url=ha_url.rstrip("/"),
        ha_token=ha_token,
        web_dir=Path(web_dir) if web_dir else None,
        assetlinks_file=Path(assetlinks) if assetlinks else None,
        door_media_dir=e.get("AIKOS_APP_DOOR_MEDIA_DIR", defaults.door_media_dir),
        entity_someone_at_door=e.get("AIKOS_APP_ENTITY_SOMEONE_AT_DOOR", defaults.entity_someone_at_door),
        entity_quiet_hours=e.get("AIKOS_APP_ENTITY_QUIET_HOURS", defaults.entity_quiet_hours),
        entity_bell_muted=e.get("AIKOS_APP_ENTITY_BELL_MUTED", defaults.entity_bell_muted),
        interim_last_message_entity=e.get("AIKOS_APP_INTERIM_LAST_MESSAGE_ENTITY", ""),
        interim_message_text_entity=e.get("AIKOS_APP_INTERIM_MESSAGE_TEXT_ENTITY", ""),
    )
