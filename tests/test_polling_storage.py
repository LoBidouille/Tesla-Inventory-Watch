"""Exercise the real HA Store rather than a mocked persistence layer."""
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from homeassistant.core import HomeAssistant
from homeassistant.util.file import WriteError

from custom_components.tesla_inventory_watch.config_flow import _defaults
from custom_components.tesla_inventory_watch.coordinator import TeslaInventoryCoordinator


class StorageTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='tesla-polling-')
        self.hass = HomeAssistant(self.temp.name)
        self.entry = SimpleNamespace(entry_id='test', async_on_unload=Mock())
        self.api = SimpleNamespace(signature='filters', async_get_inventory=AsyncMock(return_value={'total':1, 'vehicles':[{'vin':'a'}]}))
        self.coordinators = []

    def coordinator(self):
        coordinator = TeslaInventoryCoordinator(self.hass, self.entry, self.api, _defaults())
        self.coordinators.append(coordinator)
        return coordinator

    async def asyncTearDown(self):
        for coordinator in self.coordinators:
            await coordinator.async_shutdown()
        await self.hass.async_stop()
        self.temp.cleanup()

    async def test_reload_reads_persisted_deadline_and_cache(self):
        first = self.coordinator()
        await first._async_setup()
        await first._async_update_data()
        second = self.coordinator()
        await second._async_setup()
        cached = await second._async_update_data()
        self.assertEqual(cached['total'], 1)
        self.assertEqual(cached['new_vehicles'], [])
        self.assertEqual(second._next_attempt, first._next_attempt)
        self.api.async_get_inventory.assert_awaited_once()

    async def test_storage_write_error_prevents_request(self):
        coordinator = self.coordinator()
        await coordinator._async_setup()
        with patch.object(coordinator._store, '_write_prepared_data', side_effect=WriteError('disk full')):
            with self.assertLogs('homeassistant.helpers.storage', level='ERROR'):
                with self.assertRaises(OSError):
                    await coordinator._async_update_data()
        self.api.async_get_inventory.assert_not_awaited()
