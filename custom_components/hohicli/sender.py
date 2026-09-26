"""Отправка ИК-команд кондиционера через MQTT."""

import asyncio
import json
from pathlib import Path

from homeassistant.components import mqtt
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from .const import CONF_TOPIC

COMPONENT_DIR = Path(__file__).parent


class CommandSender:
    """Загружать таблицу ИК-команд и публиковать команды в MQTT."""

    def __init__(self, hass: HomeAssistant, config: ConfigType) -> None:
        self.hass = hass
        self._topic = config.get(CONF_TOPIC)
        self._commands = self.get_commands()

    def get_commands(self) -> dict:
        """Загрузить таблицу ИК-команд из JSON-файла."""
        ircommands_path = COMPONENT_DIR / "hisense_smart-dc_inverter.json"
        if not ircommands_path.exists():
            raise FileNotFoundError(f"Commands file '{ircommands_path}' not found")
        # Конструктор вызывается из executor, чтобы чтение файла не блокировало HA.
        with ircommands_path.open(encoding="utf-8") as commands_file:
            return json.load(commands_file)

    async def async_power_on(self) -> None:
        """Опубликовать команду включения."""
        await self.async_send_safe_command(self._commands["on"])

    async def async_power_off(self) -> None:
        """Опубликовать команду выключения."""
        await self.async_send_for_tya_ir(self._commands["off"])

    async def async_dimmer_change_status(self) -> None:
        """Опубликовать команду переключения диммера."""
        await self.async_send_safe_command(self._commands["dimmer"])

    async def async_enable_turbo_cool(self) -> None:
        """Опубликовать команду турборежима охлаждения."""
        await self.async_send_safe_command(self._commands["cool"]["turbo"])

    async def async_enable_turbo_heat(self) -> None:
        """Опубликовать команду турборежима нагрева."""
        await self.async_send_safe_command(self._commands["heat"]["turbo"])

    async def async_send_packet_command(
        self, operation_mode: str, fan_mode: str, target_temperature: float
    ) -> None:
        """Опубликовать команду для режима, скорости и целевой температуры."""
        await self.async_send_safe_command(
            self._commands[operation_mode][fan_mode][f"{target_temperature:g}"]
        )

    async def async_send_safe_command(self, command: str) -> None:
        """Опубликовать команду после установленной паузы."""
        # Сохраняем заданную паузу 2 секунды перед командой.
        await asyncio.sleep(2)
        await self.async_send_for_tya_ir(command)

    async def async_send_for_tya_ir(self, command: str) -> None:
        """Опубликовать ИК-код в MQTT без сохранения сообщения."""
        payload_command = json.dumps({"ir_code_to_send": command})
        # При новой подписке не нужно воспроизводить старую ИК-команду.
        await mqtt.async_publish(self.hass, self._topic, payload_command, retain=False)
