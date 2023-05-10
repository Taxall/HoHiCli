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
        await self.async_send(self._commands['off'])

    async def async_on(self):
        """Send off command."""
        _LOGGER.debug('Send on command')
        await self.async_send(self._commands['on'])

    async def async_dimmer_change_status(self):
        """Send dimmer change status command."""
        _LOGGER.debug('Send dimmer change status command')
        await self.async_send(self._commands['dimmer'])

    async def async_enable_turbo_cool(self):
        """Send enable turbo cool command."""
        _LOGGER.debug('Send enable turbo cool command')
        await self.async_send(self._commands['cool']['turbo'])

    async def async_enable_turbo_heat(self):
        """Send enable turbo heat command."""
        _LOGGER.debug('Send enable turbo heat command')
        await self.async_send(self._commands['heat']['turbo'])

    async def async_send_packet_command(self, operation_mode, fan_mode, target_temperature):
        """Send packet command."""
        _LOGGER.debug('Send packet command')
        await self.async_send(self._commands[operation_mode][fan_mode][target_temperature])

    async def async_send(self, command):
        """Send command."""
        service_data = {
            'topic': self._topic,
            'payload': command
        }
        _LOGGER.debug('Send command "%s" to topic "%s"', command, self._topic)
        await self.hass.services.async_call('mqtt', 'publish', service_data)
        await asyncio.sleep(1)

