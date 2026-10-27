import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import AsyncMock
from fastapi.testclient import TestClient
from app.config import Settings
from app.db import INTERVAL, Store
from app.main import create_app
from app.models import Search
from app.service import Service
from app.tesla import BrowserCollector, InventoryError, check_status, import_vehicles, normalize

HEADERS = {'X-Requested-With':'TeslaInventoryWatch', 'Origin':'http://testserver'}
PASSWORD = 'a-strong-test-password'


def car(index=1, **kwargs):
    return {'VIN':f'LRW3E7FA0MC{index:06}', 'Year':2023, 'InventoryPrice':32000, 'Odometer':45000,
            'PAINT':['BLACK'], 'CATEGORY':['LRRWD'], 'TrimName':'Grande Autonomie', 'City':'Aix-en-Provence', **kwargs}


def vehicles(*indices):
    return [normalize(car(i), Search()) for i in indices]


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name))

    def test_paused_by_default(self):
        self.assertIsNone(self.store.claim(now=100))
        self.assertFalse(self.store.snapshot()['enabled'])

    def test_three_checks_per_day_including_failures(self):
        claims = []
        for hour in range(24):
            claim = self.store.claim(manual=True, now=100 + hour * 3600)
            if claim:
                claims.append(claim)
                self.store.fail(claim, 'HTTP 429', now=100 + hour * 3600)
        self.assertEqual(len(claims), 3)

    def test_reload_and_recover_keep_deadline(self):
        self.store.claim(manual=True, now=100)
        restored = Store(Path(self.temp.name))
        restored.recover()
        self.assertEqual(restored.snapshot()['state']['next_check'], 100 + INTERVAL)
        self.assertIsNone(restored.claim(manual=True, now=200))
        self.assertEqual(restored.snapshot()['state']['status'], 'error')

    def test_claim_is_atomic_across_threads(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            claims = list(pool.map(lambda _: self.store.claim(manual=True, now=100), range(6)))
        self.assertEqual(sum(claim is not None for claim in claims), 1)

    def test_baseline_notifications_and_reappearing_vin(self):
        first = self.store.claim(manual=True, now=100)
        self.assertEqual(self.store.finish(first, vehicles(1), now=110), 0)
        second = self.store.claim(manual=True, now=100+INTERVAL)
        self.assertEqual(self.store.finish(second, vehicles(1,2), now=110+INTERVAL), 1)
        third = self.store.claim(manual=True, now=100+2*INTERVAL)
        self.store.finish(third, [], now=110+2*INTERVAL)
        fourth = self.store.claim(manual=True, now=100+3*INTERVAL)
        self.assertEqual(self.store.finish(fourth, vehicles(1,2), now=110+3*INTERVAL), 0)
        self.assertEqual(len(self.store.snapshot()['events']), 1)

    def test_filter_change_keeps_deadline_and_new_baseline(self):
        first = self.store.claim(manual=True, now=100)
        self.store.finish(first, vehicles(1), now=110)
        self.store.configure(Search(price_max=50000))
        self.assertIsNone(self.store.claim(manual=True, now=200))
        second = self.store.claim(manual=True, now=100+INTERVAL)
        self.assertEqual(self.store.finish(second, vehicles(2), now=110+INTERVAL), 0)

    def test_results_from_obsolete_search_are_discarded(self):
        claim = self.store.claim(manual=True, now=100)
        self.store.configure(Search(price_max=50000))
        self.assertEqual(self.store.finish(claim, vehicles(1)), 0)
        self.assertFalse(self.store.snapshot()['state']['initialized'])
        self.assertEqual(self.store.snapshot()['vehicles'], [])

    def test_import_cannot_race_a_running_check_even_after_filter_change(self):
        self.store.claim(manual=True, now=100)
        self.store.configure(Search(price_max=50000))
        with self.assertRaises(ValueError):
            self.store.import_snapshot(vehicles(1))
        self.assertEqual(self.store.snapshot()['state']['status'], 'checking')

    def test_long_retry_after_extends_deadline(self):
        claim = self.store.claim(manual=True, now=100)
        self.store.fail(claim, '429', retry_after=50000, now=110)
        self.assertEqual(self.store.snapshot()['state']['next_check'], 50110)

    def test_import_does_not_reset_network_budget(self):
        claim = self.store.claim(manual=True, now=100)
        self.store.fail(claim, 'blocked', now=110)
        self.store.import_snapshot(vehicles(1))
        self.assertEqual(self.store.snapshot()['state']['next_check'], 100 + INTERVAL)
        self.assertEqual(self.store.snapshot()['state']['source'], 'import')


class WorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_enabled_worker_collects_without_browser_and_keeps_budget(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = Settings(data_dir=Path(temp))
            store = Store(settings.data_dir)
            store.enable(True)
            collector = type('Collector', (), {'collect':AsyncMock(return_value=vehicles(1))})()
            service = Service(store, settings, collector)
            worker = asyncio.create_task(service.run())
            try:
                for _ in range(100):
                    if store.snapshot()['state']['status'] == 'ready':
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(store.snapshot()['state']['status'], 'ready')
                self.assertFalse(await service.start_check(manual=True))
                collector.collect.assert_awaited_once()
            finally:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
                await service.close()


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.collector = type('Collector', (), {'collect':AsyncMock(return_value=vehicles(1))})()
        settings = Settings(data_dir=Path(self.temp.name), allowed_hosts=('testserver',), scheduler=False)
        self.app = create_app(settings, self.collector)
        self.client = self.enterContext(TestClient(self.app))

    def setup_access(self):
        response = self.client.post('/api/setup', json={'password':PASSWORD}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_private_dashboard_and_setup_cookie(self):
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)
        self.assertTrue(self.client.get('/api/session').json()['needs_setup'])
        response = self.setup_access()
        cookie = response.headers['set-cookie'].lower()
        self.assertIn('httponly', cookie)
        self.assertIn('samesite=strict', cookie)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 200)
        self.assertEqual(self.client.post('/api/setup', json={'password':PASSWORD}, headers=HEADERS).status_code, 409)

    def test_csrf_and_hosts(self):
        self.assertEqual(self.client.post('/api/setup', json={'password':PASSWORD}).status_code, 403)
        self.assertEqual(self.client.post('/api/setup', json={'password':PASSWORD}, headers=HEADERS | {'Origin':'https://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get('/', headers={'Host':'evil.example'}).status_code, 400)

    def test_password_policy(self):
        self.assertEqual(self.client.post('/api/setup', json={'password':'short'}, headers=HEADERS).status_code, 422)

    def test_logout_and_login(self):
        self.setup_access()
        self.assertEqual(self.client.post('/api/logout', headers=HEADERS).status_code, 200)
        self.assertEqual(self.client.get('/api/dashboard').status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password':PASSWORD}, headers=HEADERS).status_code, 200)

    def test_login_throttling(self):
        self.setup_access()
        self.client.post('/api/logout', headers=HEADERS)
        for _ in range(5):
            self.assertEqual(self.client.post('/api/login', json={'password':'wrong-password-long'}, headers=HEADERS).status_code, 401)
        self.assertEqual(self.client.post('/api/login', json={'password':PASSWORD}, headers=HEADERS).status_code, 429)

    def test_configuration_and_import(self):
        self.setup_access()
        self.assertEqual(self.client.put('/api/config', json=Search().model_dump(), headers=HEADERS).status_code, 200)
        response = self.client.post('/api/import', json={'data':{'results':[car()], 'total_matches_found':1}}, headers=HEADERS)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()['new'], 0)
        self.client.post('/api/import', json={'data':{'results':[car(),car(2)],'total_matches_found':2}}, headers=HEADERS)
        data = self.client.get('/api/dashboard').json()
        self.assertEqual(len(data['events']), 1)
        self.assertEqual(data['unread_count'], 1)
        self.client.post('/api/events/read', headers=HEADERS)
        self.assertIsNotNone(self.client.get('/api/dashboard').json()['events'][0]['read_at'])

    def test_invalid_filters(self):
        self.setup_access()
        for changes in ({'price_max':100}, {'latitude':100}, {'zip':'abc'}, {'years':[1900]}):
            self.assertEqual(self.client.put('/api/config', json=Search().model_dump() | changes, headers=HEADERS).status_code, 422)

    def test_manual_check_and_budget(self):
        self.setup_access()
        self.assertEqual(self.client.post('/api/check', headers=HEADERS).status_code, 202)
        for _ in range(50):
            state = self.client.get('/api/dashboard').json()['state']
            if state['status'] != 'checking':
                break
            time.sleep(.01)
        self.assertEqual(state['status'], 'ready')
        self.assertEqual(self.client.post('/api/check', headers=HEADERS).status_code, 409)
        self.collector.collect.assert_awaited_once()

    def test_blocked_check_preserves_next_attempt(self):
        self.setup_access()
        self.collector.collect.side_effect = InventoryError('HTTP 429', 40000)
        self.client.post('/api/check', headers=HEADERS)
        for _ in range(50):
            data = self.client.get('/api/dashboard').json()
            if data['state']['status'] != 'checking':
                break
            time.sleep(.01)
        self.assertEqual(data['state']['status'], 'error')
        self.assertGreater(data['state']['next_check'] - time.time(), 39000)
        self.assertEqual(self.client.post('/api/check', headers=HEADERS).status_code, 409)
        self.collector.collect.assert_awaited_once()

    def test_static_assets_and_security_headers(self):
        response = self.client.get('/')
        self.assertIn('La bonne Tesla', response.text)
        self.assertIn("frame-ancestors 'none'", response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/static/app.js').status_code, 200)
        self.assertEqual(self.client.get('/healthz').json(), {'status':'ok'})


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def test_normalization_and_matching(self):
        self.assertEqual(normalize(car(), Search())['price'], 32000)
        self.assertIsNone(normalize(car(InventoryPrice=90000), Search()))
        self.assertIsNone(normalize(car(Year=2020), Search()))
        self.assertIsNone(normalize(car(PAINT=['WHITE']), Search()))
        with self.assertRaises(InventoryError):
            normalize(car(VIN='<script>'), Search())

    def test_invalid_or_partial_imports(self):
        for data in ({}, {'results':[], 'total_matches_found':1}, {'results':[None]}):
            with self.assertRaises(InventoryError):
                import_vehicles(data, Search())

    def test_status_and_retry_after(self):
        with self.assertRaises(InventoryError) as error:
            check_status(429, {'retry-after':'50000'})
        self.assertEqual(error.exception.retry_after, 50000)
        with self.assertRaises(InventoryError):
            check_status(403)

    async def test_browser_uses_fetch_and_pagination(self):
        cars = [car(i) for i in range(1, 26)]
        page = type('Page', (), {'evaluate':AsyncMock(side_effect=[
            {'status':200,'headers':{},'body':json.dumps({'results':cars[:24],'total_matches_found':'25'})},
            {'status':200,'headers':{},'body':json.dumps({'results':cars[24:],'total_matches_found':'25'})},
        ])})()
        result = await BrowserCollector(None).read_inventory(page, Search())
        self.assertEqual(len(result), 25)
        self.assertIn('fetch(', page.evaluate.call_args.args[0])
        self.assertIn('offset%22%3A24', page.evaluate.call_args.args[1])

    async def test_browser_refusal_stops_after_one_response(self):
        page = type('Page', (), {'evaluate':AsyncMock(return_value={'status':429,'headers':{},'body':''})})()
        with self.assertRaises(InventoryError):
            await BrowserCollector(None).read_inventory(page, Search())
        page.evaluate.assert_awaited_once()


if __name__ == '__main__':
    unittest.main()
