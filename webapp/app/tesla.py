"""Collect inventory with Chromium's own network stack and browser cookies."""
import asyncio
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import math
import os
from pathlib import Path
import re
from urllib.parse import quote, urlencode, urlsplit

from filelock import FileLock, Timeout as LockTimeout
from playwright.async_api import async_playwright, Error as BrowserError

from .models import Search

_LOGGER = logging.getLogger(__name__)

API = 'https://www.tesla.com/inventory/api/v4/inventory-results'


class InventoryError(Exception):
    def __init__(self, message, retry_after=0):
        super().__init__(message)
        self.retry_after = retry_after


def retry_after(value):
    try:
        seconds = int(value)
    except (ValueError, TypeError):
        try:
            moment = parsedate_to_datetime(value)
            if moment.tzinfo is None:
                moment = moment.replace(tzinfo=timezone.utc)
            seconds = math.ceil((moment - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            seconds = 300
    return max(60, seconds)


def check_status(status, headers=None):
    if status == 429:
        raise InventoryError('Tesla limite les requêtes (HTTP 429). Le prochain contrôle sera différé.', retry_after((headers or {}).get('retry-after', '300')))
    if status == 403:
        raise InventoryError('Tesla refuse l’accès (HTTP 403), même avec Chromium. Aucun nouvel essai immédiat.')
    if not 200 <= status < 300:
        raise InventoryError(f'Tesla a renvoyé HTTP {status}.')


def normalize(car, search):
    vin = car.get('VIN')
    if not isinstance(vin, str) or not re.fullmatch(r'[A-Za-z0-9]{17}', vin):
        raise InventoryError('Une annonce Tesla ne contient pas de VIN valide.')
    def number(value):
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None
    price = number(car.get('InventoryPrice') or car.get('PurchasePrice') or car.get('Price'))
    mileage, year = number(car.get('Odometer')), number(car.get('Year'))
    # Never alert for vehicles that contradict numeric search criteria.
    if price is None or mileage is None or year is None:
        raise InventoryError('Une annonce ne contient pas de prix, année ou kilométrage exploitable.')
    if not search.price_min <= price <= search.price_max or not search.odometer_min <= mileage <= search.odometer_max:
        return None
    if search.years and int(year) not in search.years:
        return None
    raw_paint = car.get('PAINT') or []
    paint_codes = raw_paint if isinstance(raw_paint, list) else [raw_paint]
    if search.paints and paint_codes and not set(search.paints).intersection(str(x).upper() for x in paint_codes):
        return None
    raw_category = car.get('CATEGORY') or []
    category_codes = raw_category if isinstance(raw_category, list) else [raw_category]
    if search.categories and category_codes and not set(search.categories).intersection(str(x).upper() for x in category_codes):
        return None
    options = car.get('OptionCodeData')
    paint = ', '.join(str(v) for v in paint_codes)
    if isinstance(options, list):
        paint = next((str(x.get('name') or x.get('description') or paint) for x in options if isinstance(x, dict) and x.get('group') == 'PAINT'), paint)
    return {'vin': vin, 'year': int(year), 'trim': str(car.get('TrimName') or car.get('TRIM') or ''),
            'price': price, 'mileage': mileage, 'city': str(car.get('City') or ''), 'paint': paint,
            'url': f'https://www.tesla.com/fr_FR/{search.model}/order/{quote(vin)}?redirect=no&titleStatus={search.condition}'}


def parse_page(data):
    if not isinstance(data, dict) or not isinstance(data.get('results'), list):
        raise InventoryError('La réponse Tesla ne contient pas de liste de véhicules.')
    if any(not isinstance(car, dict) for car in data['results']):
        raise InventoryError('La réponse contient une annonce invalide.')
    total = data.get('total_matches_found')
    if total is not None:
        try:
            total = int(total)
            if total < 0:
                raise ValueError()
        except (ValueError, TypeError, OverflowError) as error:
            raise InventoryError('Le total Tesla est invalide.') from error
    return data['results'], total


def import_vehicles(data, search):
    cars, total = parse_page(data)
    if total is not None and total > len(cars):
        raise InventoryError('Cet import est incomplet : ajoutez toutes les pages dans la liste results avant de l’importer.')
    vehicles = {}
    for car in cars:
        vehicle = normalize(car, search)
        if vehicle:
            vehicles[vehicle['vin']] = vehicle
    return list(vehicles.values())


def browser_proxy():
    value = os.getenv('HTTPS_PROXY') or os.getenv('https_proxy') or os.getenv('HTTP_PROXY') or os.getenv('http_proxy')
    if not value:
        return None
    parsed = urlsplit(value)
    if not parsed.hostname:
        raise InventoryError('La configuration du proxy système est invalide.')
    result = {'server': f'{parsed.scheme}://{parsed.hostname}:{parsed.port or 8080}'}
    if parsed.username:
        from urllib.parse import unquote
        result.update(username=unquote(parsed.username), password=unquote(parsed.password or ''))
    bypass = os.getenv('NO_PROXY') or os.getenv('no_proxy')
    if bypass:
        result['bypass'] = bypass
    return result


class BrowserCollector:
    def __init__(self, settings):
        self.settings = settings

    async def collect(self, search: Search):
        lock = FileLock(self.settings.data_dir / 'browser.lock')
        try:
            lock.acquire(timeout=0)
        except LockTimeout as error:
            raise InventoryError('Le profil Chromium est déjà utilisé. Fermez le navigateur de connexion manuelle.') from error
        try:
            async with asyncio.timeout(180):
                async with async_playwright() as playwright:
                    profile = self.settings.data_dir / 'browser-profile'
                    context = await playwright.chromium.launch_persistent_context(
                        str(profile), executable_path=self.settings.chromium, headless=self.settings.headless,
                        locale='fr-FR', timezone_id='Europe/Paris', viewport={'width':1440, 'height':1000},
                        proxy=browser_proxy(), args=['--disable-dev-shm-usage'],
                    )
                    try:
                        page = context.pages[0] if context.pages else await context.new_page()
                        # Rendering uses real Chromium, not APIRequestContext's separate HTTP client.
                        response = await page.goto(f'https://www.tesla.com/fr_FR/inventory/{search.condition}/{search.model}', wait_until='domcontentloaded', timeout=45000)
                        if response is None:
                            raise InventoryError('La page Tesla n’a pas répondu.')
                        check_status(response.status, await response.all_headers())
                        if urlsplit(page.url).netloc != 'www.tesla.com':
                            raise InventoryError('Tesla a redirigé la page vers une origine inattendue.')
                        await page.wait_for_timeout(2000)
                        return await self.read_inventory(page, search)
                    finally:
                        await context.close()
        except (BrowserError, TimeoutError) as error:
            _LOGGER.warning('Chromium failed (%s): %s', type(error).__name__, str(error).splitlines()[0] if str(error) else 'timeout')
            if 'ERR_CERT_' in str(error):
                raise InventoryError('Chromium refuse le certificat de la connexion. Vérifiez les autorités de confiance du serveur ou de son proxy ; la vérification TLS reste activée.') from error
            raise InventoryError('Chromium n’a pas pu terminer le contrôle (délai ou navigateur indisponible). Consultez les journaux du serveur.') from error
        finally:
            lock.release()

    async def read_inventory(self, page, search):
        vehicles, seen_pages = {}, set()
        offset, total = 0, None
        for _ in range(100):
            url = API + '?' + urlencode({'query': json.dumps(search.query(offset), separators=(',', ':'))})
            response = await page.evaluate('''async (url) => {
                const response = await fetch(url, {credentials:'include', headers:{Accept:'application/json'}});
                return {status:response.status, headers:Object.fromEntries(response.headers), body:await response.text()};
            }''', url)
            check_status(response['status'], response['headers'])
            try:
                data = json.loads(response['body'])
            except (ValueError, TypeError) as error:
                raise InventoryError('Tesla a répondu avec une page non JSON, possiblement une protection anti-bot.') from error
            cars, page_total = parse_page(data)
            if total is None:
                total = page_total
            page_vins = tuple(str(car.get('VIN')) for car in cars)
            if cars and page_vins in seen_pages:
                raise InventoryError('Tesla répète une page : le résultat incomplet est ignoré.')
            seen_pages.add(page_vins)
            for car in cars:
                vehicle = normalize(car, search)
                if vehicle:
                    vehicles[vehicle['vin']] = vehicle
            offset += len(cars)
            if total is not None and offset >= total:
                return list(vehicles.values())
            if not cars:
                if total is not None and offset < total:
                    raise InventoryError('L’inventaire est incomplet. Le précédent résultat est conservé.')
                return list(vehicles.values())
            if total is None and len(cars) < 24:
                return list(vehicles.values())
        raise InventoryError('Plus de 100 pages : affinez les filtres pour éviter un inventaire tronqué.')
