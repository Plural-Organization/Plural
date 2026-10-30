"""Every provider the host can run. Clients ask the host for this catalog and keep no copy.

Each adapter keeps the providers it serves next to its code, in a presets module. This one only
puts them in the order the settings screen shows them.
"""

from typing import Final

from plural.agent.providers import fake
from plural.agent.providers.api.anthropic import presets as anthropic
from plural.agent.providers.api.openai_compat import presets as openai_compat
from plural.agent.providers.cli import presets as cli
from plural.agent.providers.preset import Preset

PRESETS: Final[tuple[Preset, ...]] = (
    *anthropic.PRESETS,
    *cli.PRESETS,
    *openai_compat.PRESETS,
    fake.PRESET,
)

_BY_ID: Final = {preset.id: preset for preset in PRESETS}


def preset(preset_id: str) -> Preset | None:
    return _BY_ID.get(preset_id)
