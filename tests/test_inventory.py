"""Regression tests using the real Home Assistant runtime, without Tesla calls."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from aiohttp import ClientError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import UpdateFailed

from custom_components.tesla_inventory_watch.api import (
    TeslaInventoryApi, TeslaInventoryError, TeslaInventoryRateLimited, _retry_after,
)
from custom_components.tesla_inventory_watch.config_flow import (
    TeslaInventoryConfigFlow, TeslaInventoryOptionsFlow, _defaults, _validate,
)
from custom_components.tesla_inventory_watch.coordinator import TeslaInventoryCoordinator


class Response:
    def __init__(self, data=None, status=200, headers=None, raw=None):
        self.data, self.status = data, status
        self.headers, self.reason = headers or {}, 'test response'
        self.raw = raw

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def text(self):
        return self.raw if self.raw is not None else json.dumps(self.data)

    async def read(self):
        return b''


def client(*responses):
    session = Mock()
    session.get.side_effect = [Response(), *responses]  # Inventory-page warmup.
    return TeslaInventoryApi(session, _defaults()), session


def page(start, count, total=None):
    result = {'results': [{'VIN': f'VIN{i}', 'InventoryPrice': 30000} for i in range(start, start + count)]}
    if total is not None:
        result['total_matches_found'] = total
    return Response(result)


class ApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_pagination_beyond_old_four_page_limit(self):
        api, session = client(*(page(i, min(24, 121-i), '121') for i in range(0, 121, 24)))
        result = await api.async_get_inventory()
        self.assertEqual(len(result['vehicles']), 121)
        self.assertEqual(result['total'], 121)
        offsets = [json.loads(call.kwargs['params']['query'])['offset'] for call in session.get.call_args_list[1:]]
        self.assertEqual(offsets, [0, 24, 48, 72, 96, 120])

    async def test_missing_total_does_not_stop_at_first_full_page(self):
        api, _ = client(page(0, 24), page(24, 1))
        result = await api.async_get_inventory()
        self.assertEqual(result['total'], 25)

    async def test_short_page_with_more_results_keeps_paginating(self):
        api, _ = client(page(0, 2, 3), page(2, 1, 3))
        self.assertEqual(len((await api.async_get_inventory())['vehicles']), 3)

    async def test_duplicate_vins_are_not_duplicated(self):
        api, _ = client(page(0, 24, 26), page(23, 2, 26))
        result = await api.async_get_inventory()
        self.assertEqual(len(result['vehicles']), 25)

    async def test_repeated_page_is_rejected(self):
        api, _ = client(page(0, 24, 100), page(0, 24, 100))
        with self.assertRaisesRegex(TeslaInventoryError, 'repeated'):
            await api.async_get_inventory()

    async def test_repeated_final_page_is_rejected(self):
        api, _ = client(page(0, 24, 48), page(0, 24, 48))
        with self.assertRaisesRegex(TeslaInventoryError, 'repeated'):
            await api.async_get_inventory()

    async def test_pagination_limit_does_not_publish_partial_inventory(self):
        api, _ = client(*(page(i, 24, 2401) for i in range(0, 2400, 24)))
        with self.assertRaisesRegex(TeslaInventoryError, 'pagination limit'):
            await api.async_get_inventory()

    async def test_incomplete_snapshot_is_rejected(self):
        api, _ = client(page(0, 2, 10), page(0, 0, 10))
        with self.assertRaisesRegex(TeslaInventoryError, 'incomplete'):
            await api.async_get_inventory()

    async def test_invalid_responses_raise_domain_error(self):
        for data in ([], None, 'html', {'results': {}}, {'results': [None]}, {'results': [{}]}, {'results': [], 'total_matches_found': 'invalid'}, {'results': [], 'total_matches_found': -1}):
            with self.subTest(data=data):
                api, _ = client(Response(data))
                with self.assertRaises(TeslaInventoryError):
                    await api.async_get_inventory()

    async def test_non_json_response(self):
        api, _ = client(Response(raw='<html>Access denied</html>'))
        with self.assertRaisesRegex(TeslaInventoryError, 'non JSON'):
            await api.async_get_inventory()

    async def test_http_errors_preserve_status(self):
        for status in (403, 500):
            api, _ = client(Response(status=status))
            with self.assertRaises(TeslaInventoryError) as error:
                await api.async_get_inventory()
            self.assertEqual(error.exception.status, status)

    async def test_rate_limit_preserves_long_retry_after(self):
        api, _ = client(Response(status=429, headers={'Retry-After': '7200'}))
        with self.assertRaises(TeslaInventoryRateLimited) as error:
            await api.async_get_inventory()
        self.assertEqual(error.exception.retry_after, 7200)

    async def test_warmup_rate_limit_prevents_api_call(self):
        api, session = client()
        session.get.side_effect = [Response(status=429)]
        with self.assertRaises(TeslaInventoryRateLimited):
            await api.async_get_inventory()
        self.assertEqual(session.get.call_count, 1)

    async def test_network_error_wrapped(self):
        api, _ = client(ClientError('connection lost'))
        with self.assertRaises(TeslaInventoryError):
            await api.async_get_inventory()

    async def test_empty_inventory(self):
        api, _ = client(page(0, 0, '0'))
        self.assertEqual(await api.async_get_inventory(), {'total': 0, 'vehicles': []})

    def test_signature_ignores_sort_and_selection_order(self):
        cfg = _defaults()
        original = TeslaInventoryApi(None, cfg).signature
        cfg = deepcopy(cfg)
        cfg.update(sort='Odometer', order='desc', interval_minutes=60, notify_enabled=True)
        cfg['years'].reverse()
        self.assertEqual(TeslaInventoryApi(None, cfg).signature, original)
        cfg['price_max'] = 60000
        self.assertNotEqual(TeslaInventoryApi(None, cfg).signature, original)

    def test_retry_after_http_date(self):
        value = format_datetime(datetime.now(timezone.utc) + timedelta(hours=2), usegmt=True)
        self.assertTrue(7190 <= _retry_after(value) <= 7200)
        self.assertEqual(_retry_after('invalid'), 300)
        self.assertEqual(_retry_after('-1'), 60)

    def test_unexpected_paint_metadata(self):
        api, _ = client()
        self.assertEqual(api._normalize_vehicle({'VIN': 'a', 'OptionCodeData': 42})['paint'], '')


class CoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = HomeAssistant('/tmp/tesla-inventory-tests')
        self.api = SimpleNamespace(signature='filters', async_get_inventory=AsyncMock())
        self.entry = SimpleNamespace(entry_id='test', async_on_unload=Mock())
        self.coordinator = TeslaInventoryCoordinator(self.hass, self.entry, self.api, _defaults())
        self.coordinator._store = SimpleNamespace(async_save=AsyncMock(), async_load=AsyncMock(return_value=None))

    async def asyncTearDown(self):
        await self.coordinator.async_shutdown()
        await self.hass.async_stop()

    async def poll(self, *vins):
        self.api.async_get_inventory.return_value = {'total': len(vins), 'vehicles': [{'vin': vin} for vin in vins]}
        return await self.coordinator._async_update_data()

    async def test_baseline_new_vehicle_and_transient_empty(self):
        self.assertTrue((await self.poll('a'))['baseline_reset'])
        self.assertEqual((await self.poll('a'))['new_vehicles'], [])
        self.assertEqual((await self.poll('a', 'b'))['new_vehicles'], [{'vin': 'b'}])
        self.assertEqual((await self.poll())['new_vehicles'], [])
        self.assertEqual((await self.poll('a', 'b'))['new_vehicles'], [])

    async def test_filter_change_is_silent(self):
        await self.poll('a')
        self.api.signature = 'new filters'
        result = await self.poll('b')
        self.assertTrue(result['baseline_reset'])
        self.assertEqual(result['new_vehicles'], [])

    async def test_storage_failure_does_not_consume_alert(self):
        await self.poll('a')
        self.coordinator._store.async_save.side_effect = OSError('disk full')
        with self.assertRaises(OSError):
            await self.poll('a', 'b')
        self.assertEqual(self.coordinator._previous_vins, {'a'})
        self.coordinator._store.async_save.side_effect = None
        self.assertEqual((await self.poll('a', 'b'))['new_vehicles'], [{'vin': 'b'}])

    async def test_initial_storage_failure_does_not_initialize(self):
        self.coordinator._store.async_save.side_effect = OSError('disk full')
        with self.assertRaises(OSError):
            await self.poll('a')
        self.assertFalse(self.coordinator._initialized)

    async def test_error_preserves_baseline(self):
        await self.poll('a')
        self.api.async_get_inventory.side_effect = TeslaInventoryRateLimited(900)
        with self.assertRaises(UpdateFailed) as err:
            await self.coordinator._async_update_data()
        self.assertEqual(err.exception.retry_after, 900)
        self.assertEqual(self.coordinator._previous_vins, {'a'})

    async def test_saved_baseline_survives_restart(self):
        self.coordinator._store.async_load.return_value = {'initialized': True, 'current_vins': ['a'], 'signature': 'filters'}
        await self.coordinator._async_setup()
        self.assertEqual((await self.poll('a', 'b'))['new_vehicles'], [{'vin': 'b'}])

    async def test_only_new_vins_send_notifications(self):
        self.coordinator.config.update(notify_enabled=True, notify_service='notify.mobile_app_test')
        calls = []

        async def notify(call):
            calls.append(call)

        self.hass.services.async_register('notify', 'mobile_app_test', notify)
        await self.poll('a')
        await self.hass.async_block_till_done()
        self.assertEqual(calls, [])
        await self.poll('a', 'b')
        await self.hass.async_block_till_done()
        self.assertEqual(len(calls), 1)
        self.assertIn('b', calls[0].data['message'])


class FlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.hass = HomeAssistant('/tmp/tesla-inventory-flow-tests')

    async def asyncTearDown(self):
        await self.hass.async_stop()

    async def test_form_and_input_validation(self):
        flow = TeslaInventoryConfigFlow()
        flow.hass = self.hass
        self.assertEqual((await flow.async_step_user())['type'], 'form')
        cfg = _defaults()
        cfg.update(latitude=float('nan'), longitude=181, zip='abc', notify_service='light.turn_on')
        errors = _validate(cfg)
        self.assertEqual(set(errors), {'latitude', 'longitude', 'zip', 'notify_service'})

    async def test_real_form_schema_accepts_defaults(self):
        flow = TeslaInventoryConfigFlow()
        flow.hass = self.hass
        result = await flow.async_step_user()
        self.assertEqual(_validate(result['data_schema'](_defaults())), {})

    async def test_flow_errors_and_session_detach(self):
        flow = TeslaInventoryConfigFlow()
        flow.hass = self.hass
        for error, expected in ((TeslaInventoryRateLimited(), 'rate_limited'), (TeslaInventoryError('denied',403), 'forbidden'), (TeslaInventoryError('invalid'), 'cannot_connect')):
            session = Mock()
            with patch('custom_components.tesla_inventory_watch.config_flow.async_create_clientsession', return_value=session), patch.object(TeslaInventoryApi, 'async_get_inventory', side_effect=error):
                result = await flow.async_step_user(_defaults())
            self.assertEqual(result['errors']['base'], expected)
            session.detach.assert_called_once()

    async def test_successful_config_flow(self):
        flow = TeslaInventoryConfigFlow()
        flow.hass = self.hass
        with patch('custom_components.tesla_inventory_watch.config_flow._async_check_inventory', return_value={}):
            result = await flow.async_step_user(_defaults())
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['zip'], '13220')

    async def test_notification_options_do_not_require_tesla(self):
        flow = TeslaInventoryOptionsFlow()
        flow.hass = self.hass
        with patch.object(TeslaInventoryOptionsFlow, 'config_entry', new_callable=unittest.mock.PropertyMock) as entry:
            entry.return_value = SimpleNamespace(data=_defaults(), options={})
            with patch('custom_components.tesla_inventory_watch.config_flow._async_check_inventory', return_value={}) as check:
                result = await flow.async_step_init(dict(_defaults(), interval_minutes=30))
            check.assert_not_called()
        self.assertEqual(result['type'], 'create_entry')

    async def test_filter_options_require_tesla(self):
        flow = TeslaInventoryOptionsFlow()
        flow.hass = self.hass
        with patch.object(TeslaInventoryOptionsFlow, 'config_entry', new_callable=unittest.mock.PropertyMock) as entry:
            entry.return_value = SimpleNamespace(data=_defaults(), options={})
            with patch('custom_components.tesla_inventory_watch.config_flow._async_check_inventory', return_value={'base':'cannot_connect'}) as check:
                result = await flow.async_step_init(dict(_defaults(), price_max=60000))
            check.assert_awaited_once()
        self.assertEqual(result['errors'], {'base': 'cannot_connect'})


if __name__ == '__main__':
    unittest.main()
