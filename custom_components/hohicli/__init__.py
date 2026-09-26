"""HO HI Climate YAML platform."""

from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Allow Home Assistant to initialize the YAML climate platform."""
    return True
