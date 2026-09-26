"""Compatibility checks against an installed Home Assistant Core."""

import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.climate import FAN_MEDIUM
from homeassistant.components.climate.const import HVACMode
from homeassistant.const import UnitOfTemperature

from custom_components.hohicli.climate import Climate, PowerStatus
from custom_components.hohicli.sender import CommandSender


class ClimateTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.hass = MagicMock()
        self.sender = MagicMock()
        self.sender.async_power_on = AsyncMock()
        self.sender.async_power_off = AsyncMock()
        self.sender.async_dimmer_change_status = AsyncMock()
        self.sender.async_send_packet_command = AsyncMock()
        self.climate = Climate(self.hass, {"ir_mqtt_topic": "ir/send"}, self.sender)
        self.climate.async_write_ha_state = MagicMock()

    async def test_off_sends_only_off_even_when_status_is_unknown(self):
        await self.climate.async_turn_off()
        await self.climate.async_turn_off()

        self.assertEqual(self.sender.async_power_off.await_count, 2)
        self.sender.async_power_on.assert_not_awaited()

    async def test_medium_fan_maps_to_ir_table_and_celsius(self):
        self.assertEqual(self.climate.temperature_unit, UnitOfTemperature.CELSIUS)
        await self.climate.async_set_hvac_mode(HVACMode.COOL)
        await self.climate.async_set_fan_mode(FAN_MEDIUM)

        self.sender.async_send_packet_command.assert_awaited_with(
            HVACMode.COOL, "middle", 23
        )
        sensor = SimpleNamespace(
            state="77", attributes={"unit_of_measurement": UnitOfTemperature.FAHRENHEIT}
        )
        self.climate._async_update_temp(sensor)
        self.assertEqual(self.climate.current_temperature, 25)

    async def test_publish_failure_is_visible_and_status_is_not_advanced(self):
        self.sender.async_power_on.side_effect = RuntimeError("MQTT unavailable")

        with self.assertRaisesRegex(RuntimeError, "MQTT unavailable"):
            await self.climate.async_set_hvac_mode(HVACMode.COOL)

        self.assertEqual(self.climate._power_status, PowerStatus.OFF)
        self.sender.async_send_packet_command.assert_not_awaited()

    async def test_turn_off_waits_for_complete_turn_on_command(self):
        power_on_started = asyncio.Event()
        finish_power_on = asyncio.Event()
        commands = []

        async def power_on():
            commands.append("on")
            power_on_started.set()
            await finish_power_on.wait()

        async def packet(mode, fan_mode, temperature):
            commands.append((mode, fan_mode, temperature))

        async def power_off():
            commands.append("off")

        self.sender.async_power_on.side_effect = power_on
        self.sender.async_send_packet_command.side_effect = packet
        self.sender.async_power_off.side_effect = power_off

        turn_on = asyncio.create_task(self.climate.async_turn_on())
        await asyncio.wait_for(power_on_started.wait(), timeout=1)
        turn_off = asyncio.create_task(self.climate.async_turn_off())
        await asyncio.sleep(0)
        self.assertEqual(commands, ["on"])

        finish_power_on.set()
        await asyncio.wait_for(asyncio.gather(turn_on, turn_off), timeout=1)

        self.assertEqual(commands, ["on", (HVACMode.COOL, "auto", 23), "off"])
        self.assertEqual(self.climate.hvac_mode, HVACMode.OFF)
        self.assertEqual(self.climate._power_status, PowerStatus.OFF)

    async def test_set_temperature_and_mode_does_not_reacquire_lock(self):
        await asyncio.wait_for(
            self.climate.async_set_temperature(temperature=24, hvac_mode=HVACMode.HEAT),
            timeout=1,
        )
        self.sender.async_send_packet_command.assert_awaited_with(
            HVACMode.HEAT, "auto", 24
        )

    async def test_sensor_listeners_are_removed_with_entity(self):
        remove = MagicMock()
        with (
            patch.object(self.climate, "async_get_last_state", new=AsyncMock(return_value=None)),
            patch(
                "custom_components.hohicli.climate.async_track_state_change_event",
                return_value=remove,
            ) as track,
        ):
            self.hass.states.get.return_value = None
            self.climate._temperature_sensor = "sensor.room"
            self.climate._humidity_sensor = "sensor.humidity"
            await self.climate.async_added_to_hass()

        self.assertEqual(track.call_count, 2)
        for unsubscribe in self.climate._on_remove:
            unsubscribe()
        self.assertEqual(remove.call_count, 2)


class SenderTests(unittest.IsolatedAsyncioTestCase):
    async def test_publish_waits_and_preserves_payload_and_retain(self):
        sender = CommandSender(MagicMock(), {"ir_mqtt_topic": "ir/send"})
        with (
            patch("custom_components.hohicli.sender.asyncio.sleep", new=AsyncMock()),
            patch("custom_components.hohicli.sender.mqtt.async_publish", new=AsyncMock()) as publish,
        ):
            await sender.async_power_on()

        args, kwargs = publish.await_args
        self.assertEqual(args[1], "ir/send")
        self.assertEqual(json.loads(args[2]), {"ir_code_to_send": sender._commands["on"]})
        self.assertIs(kwargs["retain"], False)


if __name__ == "__main__":
    unittest.main()
