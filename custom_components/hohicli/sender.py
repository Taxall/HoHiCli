def get_command_sender(hass, topic):
    """Returning CommandSender class"""
    return CommandSender(hass, topic)

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

        await self.hass.services.async_call(
            'mqtt', 'publish', service_data)