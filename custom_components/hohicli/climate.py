"""Климатическая платформа для управления кондиционером HoHi."""

import asyncio
import logging
from enum import StrEnum
from typing import Any

from homeassistant.components.climate import (
    FAN_AUTO,
    FAN_HIGH,
    FAN_MEDIUM,
    FAN_LOW,
    ClimateEntity,
)
from homeassistant.components.climate.const import (
    ATTR_FAN_MODE,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    PRESET_BOOST,
    PRESET_NONE,
    PRESET_SLEEP,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    CONF_NAME,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    ATTR_DIMMER_STATUS,
    ATTR_LAST_ON_OPERATION,
    ATTR_POWER_STATUS,
    ATTR_TARGET_TEMPERATURE,
    CONF_HUMIDITY_SENSOR,
    CONF_MAX_TEMPERATURE,
    CONF_MIN_TEMPERATURE,
    CONF_TEMPERATURE_SENSOR,
    CONF_UNIQUE_ID,
)
from .sender import CommandSender

_LOGGER = logging.getLogger(__name__)

# В таблице ИК-кодов средняя скорость называется "middle".
IR_FAN_MODES = {FAN_MEDIUM: "middle"}


async def async_setup_platform(
    hass: HomeAssistant,
    config: ConfigType,
    async_add_entities: AddEntitiesCallback,
    discovery_info: dict | None = None,
) -> None:
    """Настроить платформу и создать сущность кондиционера."""

    command_sender = await hass.async_add_executor_job(CommandSender, hass, config)

    async_add_entities([Climate(hass, config, command_sender)])


class PowerStatus(StrEnum):
    """Сохранённое состояние питания устройства."""

    OFF = "off"
    ON = "on"


class DimmerStatus(StrEnum):
    """Сохранённое состояние диммера устройства."""

    OFF = "off"
    ON = "on"


class Climate(ClimateEntity, RestoreEntity):
    """Управлять режимами и состоянием кондиционера."""

    def __init__(
        self, hass: HomeAssistant, config: ConfigType, command_sender: CommandSender
    ) -> None:
        self.hass = hass
        self._command_sender = command_sender
        # Блокировка охватывает изменение состояния и отправку команды, чтобы
        # параллельные действия не нарушили порядок ИК-команд.
        self._command_lock = asyncio.Lock()
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

    async def async_added_to_hass(self) -> None:
        """Восстановить состояние и подписаться на датчики после добавления."""
        await super().async_added_to_hass()

        self._attr_preset_mode = PRESET_NONE

        last_state = await self.async_get_last_state()

        if last_state is not None:
            # Восстанавливаем состояние HA, не отправляя команд устройству.
            if last_state.state in self._attr_hvac_modes:
                self._attr_hvac_mode = HVACMode(last_state.state)

            if ATTR_FAN_MODE in last_state.attributes:
                self._attr_fan_mode = last_state.attributes[ATTR_FAN_MODE]

            if ATTR_TARGET_TEMPERATURE in last_state.attributes:
                self._attr_target_temperature = last_state.attributes[ATTR_TARGET_TEMPERATURE]

            if ATTR_LAST_ON_OPERATION in last_state.attributes:
                self._last_on_operation = last_state.attributes[ATTR_LAST_ON_OPERATION]

            if ATTR_POWER_STATUS in last_state.attributes:
                self._power_status = last_state.attributes[ATTR_POWER_STATUS]

            if ATTR_PRESET_MODE in last_state.attributes:
                self._attr_preset_mode = last_state.attributes[ATTR_PRESET_MODE]

            if ATTR_DIMMER_STATUS in last_state.attributes:
                self._dimmer_status = last_state.attributes[ATTR_DIMMER_STATUS]

        if self._temperature_sensor:
            self.async_on_remove(async_track_state_change_event(
                self.hass, self._temperature_sensor, self._async_temp_sensor_changed
            ))

            temp_sensor_state = self.hass.states.get(self._temperature_sensor)
            if temp_sensor_state and temp_sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(temp_sensor_state)

        if self._humidity_sensor:
            self.async_on_remove(async_track_state_change_event(
                self.hass, self._humidity_sensor, self._async_humidity_sensor_changed
            ))

            humidity_sensor_state = self.hass.states.get(self._humidity_sensor)
            if humidity_sensor_state and humidity_sensor_state.state != STATE_UNKNOWN:
                self._async_update_humidity(humidity_sensor_state)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Установить целевую температуру и при необходимости режим работы."""
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        temperature = kwargs.get(ATTR_TEMPERATURE)

        if temperature is None:
            return

        if temperature < self._attr_min_temp or temperature > self._attr_max_temp:
            _LOGGER.warning("The temperature value is out of min/max range")
            return

        # Внутри блокировки используем locked-вариант отправки: повторно брать
        # этот же lock из него нельзя.
        async with self._command_lock:
            self._attr_target_temperature = round(temperature)
            if hvac_mode is not None:
                self._set_hvac_mode(hvac_mode)
            if hvac_mode is not None or self._attr_hvac_mode != HVACMode.OFF:
                await self._async_send_command_locked()
        self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Установить режим работы."""
        async with self._command_lock:
            self._set_hvac_mode(hvac_mode)
            await self._async_send_command_locked()
        self.async_write_ha_state()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Установить скорость вентилятора."""
        async with self._command_lock:
            self._attr_fan_mode = fan_mode
            if self._attr_hvac_mode != HVACMode.OFF:
                await self._async_send_command_locked()
        self.async_write_ha_state()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Установить предустановленный режим."""
        async with self._command_lock:
            self._attr_preset_mode = preset_mode
            if self._attr_hvac_mode != HVACMode.OFF:
                await self._async_send_command_locked()
        self.async_write_ha_state()

    async def async_turn_off(self) -> None:
        """Выключить кондиционер."""
        await self.async_set_hvac_mode(HVACMode.OFF)

    async def async_turn_on(self) -> None:
        """Включить кондиционер в последнем режиме или в режиме охлаждения."""
        async with self._command_lock:
            self._set_hvac_mode(self._last_on_operation or HVACMode.COOL)
            await self._async_send_command_locked()
        self.async_write_ha_state()

    def _set_hvac_mode(self, hvac_mode: HVACMode | str) -> None:
        """Обновить режим работы; вызывающий код удерживает блокировку команд."""
        self._attr_hvac_mode = HVACMode(hvac_mode)
        if self._attr_hvac_mode != HVACMode.OFF:
            self._last_on_operation = self._attr_hvac_mode

    @callback
    def _async_temp_sensor_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Обработать изменение датчика температуры."""
        new_state = event.data["new_state"]
        if new_state is None:
            return

        self._async_update_temp(new_state)
        self.async_write_ha_state()

    @callback
    def _async_humidity_sensor_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Обработать изменение датчика влажности."""
        new_state = event.data["new_state"]
        if new_state is None:
            return

        self._async_update_humidity(new_state)
        self.async_write_ha_state()

    @callback
    def _async_update_temp(self, state: State) -> None:
        """Обновить текущую температуру по состоянию датчика."""
        try:
            if state.state != STATE_UNKNOWN and state.state != STATE_UNAVAILABLE:
                temperature = float(state.state)
                unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
                if unit in (UnitOfTemperature.CELSIUS, UnitOfTemperature.FAHRENHEIT):
                    # Сущность и таблица ИК-команд используют только градусы Цельсия.
                    temperature = TemperatureConverter.convert(
                        temperature, unit, UnitOfTemperature.CELSIUS
                    )
                self._attr_current_temperature = temperature
        except ValueError as ex:
            _LOGGER.error("Unable to update from temperature sensor: %s", ex)

    @callback
    def _async_update_humidity(self, state: State) -> None:
        """Обновить текущую влажность по состоянию датчика."""
        try:
            if state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                self._attr_current_humidity = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from humidity sensor: %s", ex)

    async def send_command_if_needed(self) -> None:
        """Отправить команду, если кондиционер включён."""
        async with self._command_lock:
            if self._attr_hvac_mode != HVACMode.OFF:
                await self._async_send_command_locked()

    async def send_command(self) -> None:
        """Отправить текущую команду."""
        async with self._command_lock:
            await self._async_send_command_locked()

    async def _async_send_command_locked(self) -> None:
        """Отправить текущую команду, когда блокировка уже захвачена."""
        if self._attr_hvac_mode == HVACMode.OFF:
            await self._command_sender.async_power_off()
            self._power_status = PowerStatus.OFF
            return

        if self._power_status == PowerStatus.OFF:
            await self._command_sender.async_power_on()
            self._power_status = PowerStatus.ON

        if self._dimmer_status == DimmerStatus.ON:
            await self._command_sender.async_dimmer_change_status()
            self._dimmer_status = DimmerStatus.OFF

        if self._attr_preset_mode == PRESET_BOOST:
            if self._attr_hvac_mode == HVACMode.COOL:
                self._attr_target_temperature = CONF_MIN_TEMPERATURE
                await self._command_sender.async_enable_turbo_cool()
            elif self._attr_hvac_mode == HVACMode.HEAT:
                self._attr_target_temperature = CONF_MAX_TEMPERATURE
                await self._command_sender.async_enable_turbo_heat()
            else:
                raise KeyError(f"Unknown hvac_mode for turbo mode\"{self._attr_hvac_mode}\"")
        else:
            # Таблица ИК-кодов называет среднюю скорость "middle" и хранит
            # температуры только в градусах Цельсия.
            await self._command_sender.async_send_packet_command(
                self._attr_hvac_mode,
                IR_FAN_MODES.get(self._attr_fan_mode, self._attr_fan_mode),
                self._attr_target_temperature,
            )

        if self._attr_preset_mode == PRESET_SLEEP and self._dimmer_status == DimmerStatus.OFF:
            await self._command_sender.async_dimmer_change_status()
            self._dimmer_status = DimmerStatus.ON

    @property
    def unique_id(self) -> str | None:
        """Вернуть уникальный идентификатор сущности."""
        return self._attr_unique_id

    @property
    def last_on_operation(self) -> HVACMode | str | None:
        """Вернуть последний режим нагрева или охлаждения."""
        return self._last_on_operation

    @property
    def extra_state_attributes(self) -> dict[str, str | int | float | None]:
        """Вернуть дополнительные атрибуты состояния."""
        return {
            ATTR_POWER_STATUS: self._power_status,
            ATTR_DIMMER_STATUS: self._dimmer_status,
            ATTR_TARGET_TEMPERATURE: self._attr_target_temperature,
            ATTR_LAST_ON_OPERATION: self._last_on_operation,
        }
