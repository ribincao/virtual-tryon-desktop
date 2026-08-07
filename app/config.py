"""Configuration loading.

The API key lives in ``config.local.toml`` at the repo root, which is gitignored.
Nothing in this module should ever write a key to a tracked file.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.local.toml"
EXAMPLE_PATH = ROOT / "config.example.toml"

# Decart bills realtime models by active generation time, not wall clock.
PRICE_PER_SEC_USD = 0.02

# Matches the SDK's own default for DecartClient(realtime_base_url=...).
REALTIME_BASE_URL = "wss://api3.decart.ai"


class ConfigError(RuntimeError):
    """Raised when config is missing or unusable. Message is shown to the user."""


@dataclass(frozen=True)
class Config:
    api_key: str
    model: str
    idle_timeout_sec: int
    max_session_cost_usd: float
    device_index: int


def load(path: Path | str | None = None) -> Config:
    path = Path(path) if path else CONFIG_PATH

    if not path.exists():
        raise ConfigError(
            f"{path.name} not found.\n\n"
            f"Copy {EXAMPLE_PATH.name} to {path.name} and fill in your API key.\n"
            f"Get one at https://platform.decart.ai (new accounts get free credits)."
        )

    data = tomllib.loads(path.read_text(encoding="utf-8"))
    decart = data.get("decart", {})

    key = str(decart.get("api_key") or "").strip()
    if not key or key.startswith("sk-...") or key.startswith("dct_your"):
        raise ConfigError(f"Set decart.api_key in {path.name}.")

    session = data.get("session", {})
    camera = data.get("camera", {})

    return Config(
        api_key=key,
        model=str(decart.get("model", "lucy-vton-latest")),
        idle_timeout_sec=int(session.get("idle_timeout_sec", 60)),
        max_session_cost_usd=float(session.get("max_session_cost_usd", 2.0)),
        device_index=int(camera.get("device_index", 0)),
    )
