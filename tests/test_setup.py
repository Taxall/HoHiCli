"""Check that Home Assistant can load the YAML-only integration."""

import asyncio
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntries
from homeassistant.core import HomeAssistant
from homeassistant import loader
from homeassistant.loader import async_setup as async_setup_loader
from homeassistant.setup import async_setup_component


class IntegrationSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_home_assistant_sets_up_hohicli_component(self):
        with tempfile.TemporaryDirectory() as config_dir:
            hass = HomeAssistant(config_dir)
            hass.config_entries = ConfigEntries(hass, {})
            async_setup_loader(hass)
            integration = loader._get_custom_components(hass)["hohicli"]
            integration._all_dependencies = set()
            hass.data[loader.DATA_INTEGRATIONS]["hohicli"] = integration

            # MQTT belongs to HA; this test checks the real hohicli loader path.
            with patch(
                "homeassistant.setup.async_process_deps_reqs", new=AsyncMock()
            ), patch(
                "homeassistant.setup.async_notify_setup_error"
            ):
                setup_result = await asyncio.wait_for(
                    async_setup_component(hass, "hohicli", {}), timeout=10
                )
                self.assertTrue(setup_result)
                self.assertIn("hohicli", hass.config.components)


if __name__ == "__main__":
    unittest.main()
