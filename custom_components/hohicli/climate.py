import logging
import asyncio

from homeassistant.backports.enum import StrEnum
from homeassistant.config_entries import ConfigEntry, DiscoveryInfoType
from homeassistant.core import callback, HomeAssistant
from homeassistant.components.climate import (
    ClimateEntity,
    FAN_AUTO,
    FAN_HIGH,
    FAN_MEDIUM,
    FAN_LOW)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.const import UnitOfTemperature
from homeassistant.helpers.event import async_track_state_change
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import ConfigType
from homeassistant.components.climate.const import (
    HVACMode,
    ATTR_HVAC_MODE,
    ATTR_FAN_MODE,
    ATTR_PRESET_MODE,
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
    CONF_UNIQUE_ID,
    ATTR_POWER_STATUS,
    ATTR_TARGET_TEMPERATURE,
    ATTR_LAST_ON_OPERATION,
    ATTR_DIMMER_STATUS)

_LOGGER = logging.getLogger(__name__)

async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,
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

class PowerStatus(StrEnum):
    """Power status for device."""

    # Device is off
    OFF = "off"

    # Device is on
    ON = "on"

class DimmerStatus(StrEnum):
    """Dimmer status for device."""

    # Dimmer is off
    OFF = "off"

    # Dimmer is on
    ON = "on"

class Climate(ClimateEntity, RestoreEntity):
    """Class for managing conditioner"""
    def __init__(self, hass, config, command_sender):
        _LOGGER.debug("init Climate")

        self.hass = hass
        self._command_sender = command_sender
        self._temp_lock = asyncio.Lock()
        self._attr_supported_features = (
                ClimateEntityFeature.TARGET_TEMPERATURE 
                | ClimateEntityFeature.FAN_MODE 
                | ClimateEntityFeature.PRESET_MODE 
                | ClimateEntityFeature.TURN_ON 
                | ClimateEntityFeature.TURN_OFF
            )
        self._attr_target_temperature_step = 1
        self._attr_temperature_unit = UnitOfTemperature.CELSIUS
        self._attr_min_temp = CONF_MIN_TEMPERATURE
        self._attr_max_temp = CONF_MAX_TEMPERATURE
        self._attr_unique_id = config.get(CONF_UNIQUE_ID)
        self._attr_name = config.get(CONF_NAME)
        self._attr_hvac_modes = [HVACMode.HEAT, HVACMode.COOL, HVACMode.OFF]
        self._attr_fan_modes = [FAN_AUTO, FAN_HIGH, FAN_MEDIUM, FAN_LOW]
        self._attr_target_temperature = 23
        self._attr_hvac_mode = HVACMode.OFF
        self._attr_fan_mode = FAN_AUTO
        self._power_status = PowerStatus.OFF
        self._dimmer_status = DimmerStatus.OFF

        self._attr_preset_mode = PRESET_NONE
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

        self._attr_preset_mode = PRESET_NONE

        last_state = await self.async_get_last_state()

        _LOGGER.debug(last_state.attributes)

        if last_state is not None:
            self._attr_hvac_mode = last_state.state

            if ATTR_FAN_MODE in last_state.attributes:
                self._attr_fan_mode = last_state.attributes[ATTR_FAN_MODE]
                _LOGGER.debug("Found '%s', set value '%s'", ATTR_FAN_MODE, last_state.attributes[ATTR_FAN_MODE])

            if ATTR_TARGET_TEMPERATURE in last_state.attributes:
                self._attr_target_temperature = last_state.attributes[ATTR_TARGET_TEMPERATURE]
                _LOGGER.debug("Found '%s', set value '%s'", ATTR_TARGET_TEMPERATURE, last_state.attributes[ATTR_TARGET_TEMPERATURE])

            if ATTR_LAST_ON_OPERATION in last_state.attributes:
                self._last_on_operation = last_state.attributes[ATTR_LAST_ON_OPERATION]
                _LOGGER.debug("Found '%s', set value '%s'", ATTR_LAST_ON_OPERATION, last_state.attributes[ATTR_LAST_ON_OPERATION])

            if ATTR_POWER_STATUS in last_state.attributes:
                self._power_status = last_state.attributes[ATTR_POWER_STATUS]
                _LOGGER.debug("Found '%s', set value '%s'", ATTR_POWER_STATUS, last_state.attributes[ATTR_POWER_STATUS])

            if ATTR_PRESET_MODE in last_state.attributes:
                self._attr_preset_mode = last_state.attributes[ATTR_PRESET_MODE]
                _LOGGER.debug("Found '%s', set value '%s'", ATTR_PRESET_MODE, last_state.attributes[ATTR_PRESET_MODE])

            if ATTR_DIMMER_STATUS in last_state.attributes:
                self._dimmer_status = last_state.attributes[ATTR_DIMMER_STATUS]
                _LOGGER.debug("Found '%s', set value '%s'", ATTR_DIMMER_STATUS, last_state.attributes[ATTR_DIMMER_STATUS])

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

        await self.send_command_if_needed()

        await self.async_update_ha_state()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set operation mode."""

        self._attr_hvac_mode = hvac_mode

        if self._attr_hvac_mode != HVACMode.OFF:
            self._last_on_operation = hvac_mode

        await self.send_command()
        await self.async_update_ha_state()

    async def async_set_fan_mode(self, fan_mode):
        """Set fan mode."""
        self._attr_fan_mode = fan_mode

        await self.send_command_if_needed()
        await self.async_update_ha_state()

    async def async_set_preset_mode(self, preset_mode: str):
        """Set preset mode."""
        self._attr_preset_mode = preset_mode

        await self.send_command_if_needed()
        await self.async_update_ha_state()

    async def async_turn_off(self):
        """Turn off."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    def turn_off(self) -> None:
        """Turn the entity off."""
        asyncio.run(self.async_turn_off()) 

    async def async_turn_on(self):
        """Turn on."""
        if self._last_on_operation is not None:
            await self.async_set_hvac_mode(self._last_on_operation)
        else:
            await self.async_set_hvac_mode(HVACMode.COOL)

    def turn_on(self) -> None:
        """Turn the entity on."""
        asyncio.run(self.async_turn_on()) 

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

    async def send_command_if_needed(self):
        """Sending command if needed."""
        if self._attr_hvac_mode != HVACMode.OFF:
            await self.send_command()

    async def send_command(self):
        """Sending command."""
        async with self._temp_lock:
            try:
                if self._power_status == PowerStatus.OFF:
                    await self._command_sender.async_power_on()
                    self._power_status = PowerStatus.ON
                    _LOGGER.debug("Power on")

                if self._dimmer_status == DimmerStatus.ON:
                    await self._command_sender.async_dimmer_change_status()
                    self._dimmer_status = DimmerStatus.OFF
                    _LOGGER.debug("Dimmer off")

                if self._attr_hvac_mode == HVACMode.OFF:
                    await self._command_sender.async_power_off()
                    self._power_status = PowerStatus.OFF
                    _LOGGER.debug("Power off")
                    return

                if self._attr_preset_mode == PRESET_BOOST:
                    if self._attr_hvac_mode == HVACMode.COOL:
                        self._attr_target_temperature = CONF_MIN_TEMPERATURE
                        await self._command_sender.async_enable_turbo_cool()
                    elif self._attr_hvac_mode == HVACMode.HEAT:
                        self._attr_target_temperature = CONF_MAX_TEMPERATURE
                        await self._command_sender.async_enable_turbo_heat()
                    else:
                        raise KeyError(f'Unknown hvac_mode for turbo mode"{self._attr_hvac_mode}"')
                else:
                    await self._command_sender.async_send_packet_command(self._attr_hvac_mode, self._attr_fan_mode, self._attr_target_temperature)

                _LOGGER.debug("preset_mode: '%s', dimmer_status: '%s'", self._attr_preset_mode, self._dimmer_status)
                if self._attr_preset_mode == PRESET_SLEEP and self._dimmer_status == DimmerStatus.OFF:
                    await self._command_sender.async_dimmer_change_status()
                    self._dimmer_status = DimmerStatus.ON
                    _LOGGER.debug("Dimmer on")

                await self.async_update_ha_state()
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
  
    @property
    def extra_state_attributes(self):
        """Return the state attributes."""
        return {
            ATTR_POWER_STATUS:  self._power_status,
            ATTR_DIMMER_STATUS: self._dimmer_status,
            ATTR_TARGET_TEMPERATURE: self._attr_target_temperature,
            ATTR_LAST_ON_OPERATION: self._last_on_operation
        }