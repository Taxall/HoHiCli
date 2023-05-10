import logging
import asyncio

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import callback, HomeAssistant
from homeassistant.components.climate import (
    ClimateEntity,
    FAN_AUTO,
    FAN_HIGH,
    FAN_MEDIUM,
    FAN_LOW)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import TEMP_CELSIUS
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType
from homeassistant.components.climate.const import (
    HVACMode,
    ATTR_HVAC_MODE,
    ClimateEntityFeature,
    PRESET_BOOST,
    PRESET_NONE,
    PRESET_SLEEP)
from homeassistant.const import (
    CONF_NAME,
    STATE_UNKNOWN,
    STATE_UNAVAILABLE,
    ATTR_TEMPERATURE)
from .sender import CommandSender
from .const import (
    CONF_TEMPERATURE_SENSOR,
    CONF_HUMIDITY_SENSOR,
    CONF_MIN_TEMPERATURE,
    CONF_MAX_TEMPERATURE,
    CONF_UNIQUE_ID)

COMPONENT_ABS_DIR = os.path.dirname(os.path.abspath(__file__))

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the hisense climate."""

    command_sender = CommandSender(hass, config)

    async_add_entities(
        [
            Climate(hass, config, command_sender)
        ]
    )

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the hisense climate devices config entry."""
    await async_setup_platform(hass, config_entry, async_add_entities)


class Climate(ClimateEntity, RestoreEntity):
    """Class for managing conditioner"""
    def __init__(self, hass, config, command_sender):
        _LOGGER.debug("init Climate")

        self.hass = hass

        self._temp_lock = asyncio.Lock()

        self._attr_supported_features = ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.FAN_MODE | ClimateEntityFeature.PRESET_MODE

        self.target_temperature_step = 1
        self._dimmer_on = False
        self._attr_temperature_unit = TEMP_CELSIUS
        self._attr_min_temp = CONF_MIN_TEMPERATURE
        self._attr_max_temp = CONF_MAX_TEMPERATURE
        self._controller = command_sender
        self._attr_unique_id = config.get(CONF_UNIQUE_ID)
        self._attr_name = config.get(CONF_NAME)
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
        self._attr_fan_modes = [FAN_AUTO, FAN_HIGH, FAN_MEDIUM, FAN_LOW]
        self._attr_target_temperature = 23
        self._attr_hvac_mode = HVACMode.OFF
        self._last_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = self._attr_fan_modes[0]

        self._attr_preset_mode = None
        self._attr_preset_modes = [PRESET_NONE, PRESET_BOOST, PRESET_SLEEP]

        self._temperature_sensor = config.get(CONF_TEMPERATURE_SENSOR)
        self._humidity_sensor = config.get(CONF_HUMIDITY_SENSOR)

        self._last_on_operation = None
        self._attr_current_temperature = None
        self._attr_current_humidity = None

        self._attr_temperature_unit = hass.config.units.temperature_unit

    async def async_added_to_hass(self):
        """Run when entity about to be added."""

        _LOGGER.debug("async_added_to_hass")

        await super().async_added_to_hass()

        last_state = await self.async_get_last_state()

        _LOGGER.debug(last_state.attributes)

        if last_state is not None:
            self._attr_hvac_mode = last_state.state

            if 'fan_mode' in last_state.attributes:
                self._attr_fan_mode = last_state.attributes['fan_mode']

            if 'target_temperature' in last_state.attributes:
                self._attr_target_temperature = last_state.attributes['target_temperature']

            if 'last_on_operation' in last_state.attributes:
                self._last_on_operation = last_state.attributes['last_on_operation']

        if self._temperature_sensor:
            async_track_state_change(self.hass, self._temperature_sensor, 
                                     self._async_temp_sensor_changed)

            temp_sensor_state = self.hass.states.get(self._temperature_sensor)
            if temp_sensor_state and temp_sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(temp_sensor_state)

        if self._humidity_sensor:
            async_track_state_change(self.hass, self._humidity_sensor, 
                                     self._async_humidity_sensor_changed)

            humidity_sensor_state = self.hass.states.get(self._humidity_sensor)
            if humidity_sensor_state and humidity_sensor_state.state != STATE_UNKNOWN:
                self._async_update_humidity(humidity_sensor_state)

    async def async_set_temperature(self, **kwargs):
        """Set new target temperatures."""
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        if temperature < self._attr_min_temp or temperature > self._attr_max_temp:
            _LOGGER.warning('The temperature value is out of min/max range')
            return

        self._attr_target_temperature = round(temperature)

        if hvac_mode:
            await self.async_set_hvac_mode(hvac_mode)
            return

        if self._attr_hvac_mode != HVACMode.OFF:
            await self.send_command()

        await self.async_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set operation mode."""
        self._last_hvac_mode = self._attr_hvac_mode
        self._attr_hvac_mode = hvac_mode

        if self._attr_hvac_mode != HVACMode.OFF:
            self._last_on_operation = hvac_mode

        await self.send_command()
        await self.async_update_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        self._attr_fan_mode = fan_mode

        if self._attr_hvac_mode != HVACMode.OFF:
            await self.send_command()
        await self.async_update_ha_state()

    async def async_set_preset_mode(self, preset_mode: str):
        """Set preset mode."""
        self._attr_preset_mode = preset_mode

        if self._attr_hvac_mode != HVACMode.OFF:
            if self._attr_preset_mode is PRESET_SLEEP and self._dimmer_on is False:
                await self._controller.async_dimmer_change_status()
                self._dimmer_on = True
            elif self._attr_preset_mode is PRESET_BOOST:
                self._dimmer_on = False
                if self._attr_hvac_mode == HVACMode.COOL:
                    self._attr_target_temperature = 16
                    await self._controller.async_enable_turbo_cool()
                elif self._attr_hvac_mode == HVACMode.HEAT:
                    self._attr_target_temperature = 30
                    await self._controller.async_enable_turbo_heat()
                else:
                    raise KeyError(f'Unknown hvac_mode "{self._attr_hvac_mode}"')
        await self.async_update_ha_state()

    async def async_turn_off(self):
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self):
        """Turn on."""
        if self._last_on_operation is not None:
            await self.async_set_hvac_mode(self._last_on_operation)
        else:
            await self.async_set_hvac_mode(HVACMode.COOL)

    async def _async_temp_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature sensor changes."""
        if new_state is None:
            return

        self._async_update_temp(new_state)
        await self.async_update_ha_state()

    async def _async_humidity_sensor_changed(self, entity_id, old_state, new_state):
        """Handle humidity sensor changes."""
        if new_state is None:
            return

        self._async_update_humidity(new_state)
        await self.async_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from temperature sensor."""
        try:
            if state.state != STATE_UNKNOWN and state.state != STATE_UNAVAILABLE:
                self._attr_current_temperature = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)

    @callback
    def _async_update_humidity(self, state):
        """Update thermostat with latest state from humidity sensor."""
        try:
            if state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._attr_current_humidity = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from humidity sensor: %s", ex)

    async def send_command(self):
        """Sending command."""
        async with self._temp_lock:
            try:
                if self._attr_hvac_mode == HVACMode.OFF:
                    await self._controller.async_off()
                    return

                if self._last_hvac_mode is None or self._last_hvac_mode == HVACMode.OFF:
                    await self._controller.async_on()

                if self._dimmer_on is True:
                    await self._controller.async_dimmer_change_status()
                    self._dimmer_on = False

                await self._controller.async_send_packet_command(self._attr_hvac_mode, self._attr_fan_mode, self._attr_target_temperature)

                if self._attr_preset_mode is PRESET_SLEEP and self._dimmer_on is False:
                    await self._controller.async_dimmer_change_status()
                    self._dimmer_on = True
            except Exception as ex: # pylint: disable=broad-except
                _LOGGER.exception(ex)

    @property
    def unique_id(self):
        """Return a unique ID."""
        return self._attr_unique_id

    @property
    def last_on_operation(self):
        """Return the last non-idle operation ie. heat, cool."""
        return self._last_on_operation
