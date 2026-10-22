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
        self.clock = 1700000000.0
        self.clock_patch = patch('custom_components.tesla_inventory_watch.coordinator.time.time', side_effect=lambda: self.clock)
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.hass = HomeAssistant('/tmp/tesla-inventory-tests')
        self.api = SimpleNamespace(signature='filters', async_get_inventory=AsyncMock())
        self.entry = SimpleNamespace(entry_id='test', async_on_unload=Mock())
        self.coordinator = TeslaInventoryCoordinator(self.hass, self.entry, self.api, _defaults())
        self.assertEqual(self.coordinator._store.key, 'tesla_inventory_watch.test')
        self.coordinator._store = SimpleNamespace(async_save=AsyncMock(), async_load=AsyncMock(return_value=None))
        self.coordinator._async_verify_saved_state = AsyncMock()

    async def asyncTearDown(self):
        await self.coordinator.async_shutdown()
        await self.hass.async_stop()

    async def poll(self, *vins, advance=True):
        if advance:
            self.clock += 8 * 3600
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
        self.coordinator._store.async_save.side_effect = [None, OSError('disk full')]
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
        self.clock += 8 * 3600
        self.api.async_get_inventory.side_effect = TeslaInventoryRateLimited(900)
        with self.assertRaises(UpdateFailed) as err:
            await self.coordinator._async_update_data()
        self.assertEqual(err.exception.retry_after, 8 * 3600)
        self.assertEqual(self.coordinator._previous_vins, {'a'})

    async def test_saved_baseline_survives_restart(self):
        self.coordinator._store.async_load.return_value = {'initialized': True, 'current_vins': ['a'], 'signature': 'filters'}
        await self.coordinator._async_setup()
        self.assertEqual((await self.poll('a', 'b'))['new_vehicles'], [{'vin': 'b'}])

    async def test_budget_allows_only_three_checks_in_24_hours(self):
        for hour in range(24):
            await self.poll('a', advance=False)
            self.clock += 3600
        self.assertEqual(self.api.async_get_inventory.await_count, 3)

    async def test_manual_refresh_returns_cache_without_network_or_old_alerts(self):
        await self.poll('a')
        await self.poll('a', 'b')
        result = await self.poll('a', 'b', 'c', advance=False)
        self.assertEqual(self.api.async_get_inventory.await_count, 2)
        self.assertEqual(result['new_vehicles'], [])
        self.assertEqual(len(result['vehicles']), 2)

    async def test_budget_survives_restart(self):
        await self.poll('a')
        persisted = self.coordinator._store.async_save.call_args.args[0]
        self.coordinator._store.async_load.return_value = persisted
        self.coordinator._next_attempt = 0
        self.coordinator._cached_data = None
        await self.coordinator._async_setup()
        await self.poll('b', advance=False)
        self.assertEqual(self.api.async_get_inventory.await_count, 1)

    async def test_forbidden_consumes_attempt_and_survives_restart(self):
        self.api.async_get_inventory.side_effect = TeslaInventoryError('denied', 403)
        for _ in range(2):
            with self.assertRaises(UpdateFailed) as error:
                await self.coordinator._async_update_data()
            self.assertEqual(error.exception.retry_after, 8 * 3600)
        persisted = self.coordinator._store.async_save.call_args.args[0]
        self.coordinator._store.async_load.return_value = persisted
        await self.coordinator._async_setup()
        with self.assertRaises(UpdateFailed):
            await self.coordinator._async_update_data()
        self.assertEqual(self.api.async_get_inventory.await_count, 1)
        self.assertFalse(persisted['initialized'])

    async def test_long_tesla_retry_after_is_respected(self):
        self.api.async_get_inventory.side_effect = TeslaInventoryRateLimited(12 * 3600)
        with self.assertRaises(UpdateFailed) as error:
            await self.coordinator._async_update_data()
        self.assertEqual(error.exception.retry_after, 12 * 3600)

    async def test_rate_limit_error_includes_local_deadline(self):
        self.hass.config.time_zone = 'Europe/Paris'
        self.api.async_get_inventory.side_effect = TeslaInventoryRateLimited(300)
        with self.assertRaises(UpdateFailed) as error:
            await self.coordinator._async_update_data()
        self.assertEqual(error.exception.translation_key, 'rate_limited')
        next_check = error.exception.translation_placeholders['next_check']
        self.assertEqual(datetime.fromisoformat(next_check).timestamp(), self.clock + 8 * 3600)
        self.assertTrue(next_check.endswith('+01:00'))
        self.assertIn('HTTP 429', str(error.exception))
        self.assertIn(next_check, str(error.exception))

    async def test_old_rate_limit_state_keeps_its_deadline(self):
        deadline = self.clock + 3600
        self.coordinator._store.async_load.return_value = {
            'next_attempt': deadline,
            'last_error': 'Tesla inventory request failed: Tesla rate limit reached',
        }
        await self.coordinator._async_setup()
        with self.assertRaises(UpdateFailed) as error:
            await self.coordinator._async_update_data()
        self.assertEqual(error.exception.translation_key, 'rate_limited')
        self.assertEqual(error.exception.retry_after, 3600)
        self.assertEqual(self.coordinator._next_attempt, deadline)
        self.api.async_get_inventory.assert_not_awaited()

    async def test_setup_retry_preserves_translated_rate_limit(self):
        from homeassistant.config_entries import ConfigEntryState
        from homeassistant.exceptions import ConfigEntryNotReady
        self.entry.state = ConfigEntryState.SETUP_IN_PROGRESS
        self.api.async_get_inventory.side_effect = TeslaInventoryRateLimited(300)
        for _ in range(2):
            with self.assertRaises(ConfigEntryNotReady) as error:
                await self.coordinator.async_config_entry_first_refresh()
            # Older HA versions preserve the coordinator reason as the cause.
            reason = error.exception
            if reason.translation_key is None:
                reason = reason.__cause__
            self.assertEqual(reason.translation_key, 'rate_limited')
            self.assertIn('next_check', reason.translation_placeholders)
            # The isolated test has no HA translation cache; the coordinator
            # still supplies a complete fallback for logs and older HA versions.
            self.assertIn(reason.translation_placeholders['next_check'], str(self.coordinator.last_exception))
            # The next setup invocation reloads the same saved state.
            self.coordinator._store.async_load.return_value = self.coordinator._store.async_save.call_args.args[0]
        self.api.async_get_inventory.assert_awaited_once()

    async def test_filter_change_does_not_bypass_budget_or_show_old_search(self):
        await self.poll('a')
        self.api.signature = 'new filters'
        with self.assertRaises(UpdateFailed):
            await self.poll('b', advance=False)
        self.assertEqual(self.api.async_get_inventory.await_count, 1)
        result = await self.poll('b')
        self.assertTrue(result['baseline_reset'])
        self.assertEqual(result['new_vehicles'], [])

    async def test_failed_reservation_does_not_call_tesla(self):
        self.coordinator._store.async_save.side_effect = OSError('disk full')
        with self.assertRaises(OSError):
            await self.poll('a')
        self.api.async_get_inventory.assert_not_awaited()

    async def test_unpersisted_checkpoint_does_not_call_tesla(self):
        self.coordinator._async_verify_saved_state.side_effect = OSError('checkpoint mismatch')
        with self.assertRaises(OSError):
            await self.poll('a')
        self.api.async_get_inventory.assert_not_awaited()

    async def test_concurrent_refreshes_share_one_attempt(self):
        import asyncio
        self.api.async_get_inventory.return_value = {'total': 1, 'vehicles': [{'vin': 'a'}]}
        await asyncio.gather(*(self.coordinator._async_update_data() for _ in range(3)))
        self.assertEqual(self.api.async_get_inventory.await_count, 1)

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
        values = _defaults()
        values.pop('interval_minutes')
        self.assertEqual(_validate(result['data_schema'](values)), {})

    async def test_successful_config_flow_has_no_network_call(self):
        flow = TeslaInventoryConfigFlow()
        flow.hass = self.hass
        with patch.object(TeslaInventoryApi, 'async_get_inventory') as fetch:
            result = await flow.async_step_user(_defaults())
        fetch.assert_not_called()
        self.assertEqual(result['type'], 'create_entry')
        self.assertEqual(result['data']['zip'], '13220')
        self.assertEqual(result['data']['interval_minutes'], 480)

    async def test_all_options_are_saved_without_calling_tesla(self):
        for changes in ({'interval_minutes': 5}, {'price_max': 60000}):
            flow = TeslaInventoryOptionsFlow()
            flow.hass = self.hass
            with patch.object(TeslaInventoryOptionsFlow, 'config_entry', new_callable=unittest.mock.PropertyMock) as entry:
                entry.return_value = SimpleNamespace(data=_defaults(), options={})
                with patch.object(TeslaInventoryApi, 'async_get_inventory') as fetch:
                    result = await flow.async_step_init(dict(_defaults(), **changes))
            fetch.assert_not_called()
            self.assertEqual(result['type'], 'create_entry')
            self.assertEqual(result['data']['interval_minutes'], 480)

    async def test_configuration_form_does_not_offer_short_intervals(self):
        flow = TeslaInventoryConfigFlow()
        flow.hass = self.hass
        result = await flow.async_step_user()
        self.assertNotIn('interval_minutes', {str(key) for key in result['data_schema'].schema})


if __name__ == '__main__':
    unittest.main()
