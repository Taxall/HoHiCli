import logging
import asyncio
import os
import os.path
import json

from .const import CONF_TOPIC

COMPONENT_ABS_DIR = os.path.dirname(os.path.abspath(__file__))
_LOGGER = logging.getLogger(__name__)

class CommandSender():
    """Class sending command to mqtt"""
    def __init__(self, hass, config):
        self.hass = hass
        self._topic = config.get(CONF_TOPIC)
        self._commands = self.get_commands()

    def get_commands(self):
        """Initialize IR commands"""
        ircommands_path = os.path.join(COMPONENT_ABS_DIR, 'hisense_smart-dc_inverter.json')
        if not os.path.exists(ircommands_path):
            raise FileNotFoundError(f"Commands file '{ircommands_path}' not found")
        with open(ircommands_path, mode="r", encoding="utf-8") as json_obj:
            return json.load(json_obj)

    async def async_off(self):
        """Send off command."""
        _LOGGER.debug('Send off command')
        await self.async_send_for_tya_ir(self._commands['off'])

    async def async_on(self):
        """Send off command."""
        _LOGGER.debug('Send on command')
        await self.async_send_for_tya_ir(self._commands['on'])

    async def async_dimmer_change_status(self):
        """Send dimmer change status command."""
        _LOGGER.debug('Send dimmer change status command')
        await self.async_send_for_tya_ir(self._commands['dimmer'])

    async def async_enable_turbo_cool(self):
        """Send enable turbo cool command."""
        _LOGGER.debug('Send enable turbo cool command')
        await self.async_send_for_tya_ir(self._commands['cool']['turbo'])

    async def async_enable_turbo_heat(self):
        """Send enable turbo heat command."""
        _LOGGER.debug('Send enable turbo heat command')
        await self.async_send_for_tya_ir(self._commands['heat']['turbo'])

    async def async_send_for_tya_ir_packet_command(self, operation_mode, fan_mode, target_temperature):
        """Send packet command."""
        _LOGGER.debug('Send packet command for operation mode: "%s",  fan_mode "%s", target temperature "%s"', operation_mode, fan_mode, target_temperature)

        await self.async_send_for_tya_ir(self._commands[operation_mode][fan_mode][f'{target_temperature:g}'])

    async def async_send_for_tya_ir(self, command):
        """Send command."""

        payload_command = f'{{"ir_code_to_send": "{command}"}}'

        service_data = {
            'topic': self._topic,
            'payload': payload_command
        }
        _LOGGER.debug('Send data "%s" to mqtt"', service_data)
        await self.hass.services.async_call('mqtt', 'publish', service_data)
        await asyncio.sleep(1)
