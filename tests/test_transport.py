"""Verify Chrome transport settings and lazy dependency loading."""
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientError, ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from custom_components.tesla_inventory_watch import async_setup_entry
from custom_components.tesla_inventory_watch.config_flow import TeslaInventoryConfigFlow, _defaults
from custom_components.tesla_inventory_watch.transport import ChromeSession


class TransportTests(unittest.IsolatedAsyncioTestCase):
    def make_session(self):
        requests = Mock()
        requests.RequestsError = RuntimeError
        requests.AsyncSession.return_value = SimpleNamespace(get=AsyncMock(), close=AsyncMock())
        return ChromeSession(requests, '/trusted/ca.pem'), requests

    async def test_chrome_fingerprint_trust_and_no_retries(self):
        session, requests = self.make_session()
        kwargs = requests.AsyncSession.call_args.kwargs
        self.assertEqual(kwargs['impersonate'], 'chrome')
        self.assertEqual(kwargs['verify'], '/trusted/ca.pem')
        self.assertEqual(kwargs['retry'], 0)
        self.assertTrue(kwargs['trust_env'])
        await session.close()

    async def test_response_adapter_and_timeout(self):
        session, requests = self.make_session()
        requests.AsyncSession.return_value.get.return_value = SimpleNamespace(
            status_code=403, headers={'Retry-After':'300'}, reason='Forbidden', text='denied', content=b'denied'
        )
        async with session.get('https://www.tesla.com/', timeout=ClientTimeout(total=30)) as response:
            self.assertEqual(response.status, 403)
            self.assertEqual(await response.text(), 'denied')
            self.assertEqual(await response.read(), b'denied')
        self.assertEqual(requests.AsyncSession.return_value.get.call_args.kwargs['timeout'], 30)
        await session.close()

    async def test_native_errors_are_wrapped(self):
        session, requests = self.make_session()
        requests.AsyncSession.return_value.get.side_effect = RuntimeError('network failed')
        with self.assertRaises(ClientError):
            async with session.get('https://www.tesla.com/'):
                pass
        await session.close()

    async def test_close_is_idempotent(self):
        session, requests = self.make_session()
        await session.close()
        await session.close()
        requests.AsyncSession.return_value.close.assert_awaited_once()

    async def test_missing_native_library_does_not_break_config_flow(self):
        hass = HomeAssistant('/tmp/tesla-browser-tests')
        try:
            with patch('custom_components.tesla_inventory_watch.transport._load_browser', side_effect=ImportError('missing binary')):
                flow = TeslaInventoryConfigFlow()
                flow.hass = hass
                self.assertEqual((await flow.async_step_user(_defaults()))['type'], 'create_entry')
                entry = SimpleNamespace(data=_defaults(), options={}, async_on_unload=Mock())
                with self.assertRaises(ConfigEntryNotReady):
                    await async_setup_entry(hass, entry)
        finally:
            await hass.async_stop()
