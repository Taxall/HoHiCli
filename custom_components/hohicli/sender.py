import logging

def get_command_sender(hass, topic):
    """Returning CommandSender class"""
    return CommandSender(hass, topic)

_LOGGER = logging.getLogger(__name__)

class CommandSender():
    """Class sending command to mqtt"""
    def __init__(self, hass, topic):
        self.hass = hass
        self._topic = topic

    async def send(self, command):
        """Send a command."""
        service_data = {
            'topic': self._topic,
            'payload': command
        }

        _LOGGER.debug('Send command "%s" to topic "%s"', command, self._topic)

        await self.hass.services.async_call('mqtt', 'publish', service_data)
