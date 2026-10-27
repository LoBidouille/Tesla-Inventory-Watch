import asyncio
import json
import secrets
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from playwright.async_api import async_playwright

async def check(base):
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.getenv('CHROMIUM_EXECUTABLE', '/usr/bin/chromium'), headless=True, args=['--disable-dev-shm-usage'])
        page = await browser.new_page(viewport={'width':1440,'height':1080}, device_scale_factor=1)
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        await page.goto(base + '/')
        await page.get_by_text('Faites comme chez vous.', exact=True).wait_for()
        password = secrets.token_urlsafe(24)
        await page.locator('#password').fill(password)
        await page.locator('#password-confirm').fill(password)
        await page.locator('#auth-submit').click()
        await page.locator('#application').wait_for(state='visible')
        if os.getenv('SCREENSHOT_DIR'):
            await page.screenshot(path=str(Path(os.environ['SCREENSHOT_DIR']) / 'dashboard.png'), full_page=True)
        await page.locator('nav [data-view=search]').click()
        await page.locator('[name=price_max]').fill('46000')
        await page.get_by_role('button',name='Enregistrer ma recherche').click()
        await page.get_by_text('Recherche enregistrée. Une référence sera créée au prochain contrôle.',exact=True).wait_for()
        await page.locator('nav [data-view=help]').click()
        await page.locator('summary').click()
        car = {'VIN':'LRW3E7FA0MC000001','Year':2023,'InventoryPrice':32000,'Odometer':45000,'PAINT':['BLACK'],'CATEGORY':['LRRWD'],'TrimName':'Grande Autonomie','City':'Aix-en-Provence'}
        data = {'results':[car],'total_matches_found':1}
        await page.locator('#import-json').fill(json.dumps(data))
        await page.locator('#import-button').click()
        await page.get_by_text('1 véhicule(s) importé(s), 0 nouvelle(s) annonce(s).',exact=True).wait_for()
        data['results'].append(car | {'VIN':'LRW3E7FA0MC000002','InventoryPrice':35000})
        data['total_matches_found'] = 2
        await page.locator('#import-json').fill(json.dumps(data))
        await page.locator('#import-button').click()
        await page.get_by_text('2 véhicule(s) importé(s), 1 nouvelle(s) annonce(s).',exact=True).wait_for()
        await page.locator('nav [data-view=dashboard]').click()
        await page.locator('.vehicle-card').first.wait_for()
        assert await page.locator('.vehicle-card').count() == 2
        if os.getenv('SCREENSHOT_DIR'):
            await page.screenshot(path=str(Path(os.environ['SCREENSHOT_DIR']) / 'vehicles.png'), full_page=True)
        await page.set_viewport_size({'width':390,'height':844})
        if os.getenv('SCREENSHOT_DIR'):
            await page.evaluate('window.scrollTo(0,0)')
            await page.screenshot(path=str(Path(os.environ['SCREENSHOT_DIR']) / 'mobile.png'), full_page=True)
        assert await page.evaluate('document.documentElement.scrollWidth <= window.innerWidth'), 'Mobile overflow'
        await page.locator('nav [data-view=history]').click()
        assert await page.locator('.event-row').count() == 1
        await page.locator('#mark-read').click()
        await page.locator('#nav-count').wait_for(state='hidden')
        await page.locator('#account-logout').click()
        await page.locator('#auth-screen').wait_for(state='visible')
        await page.locator('#password').fill(password)
        await page.locator('#auth-submit').click()
        await page.locator('#application').wait_for(state='visible')
        await page.set_viewport_size({'width':1440,'height':1080})
        await page.locator('#logout').click()
        await page.locator('#auth-screen').wait_for(state='visible')
        await page.locator('#password').fill(password)
        await page.locator('#auth-submit').click()
        await page.locator('#application').wait_for(state='visible')
        assert not errors, errors
        print('PASS: real Chromium setup, login, editing, two imports, new-VIN alert, history, read state, logout/login, desktop/mobile and no JavaScript errors')
        await browser.close()

def main():
    with tempfile.TemporaryDirectory(prefix='inventory-ui-') as temp:
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        base = f'http://127.0.0.1:{port}'
        environment = dict(os.environ, DATA_DIR=temp, PORT=str(port), HOST='127.0.0.1', ALLOWED_HOSTS='127.0.0.1,localhost', PUBLIC_URL='', COOKIE_SECURE='0')
        with open(Path(temp) / 'server.log', 'w+') as log:
            process = subprocess.Popen([sys.executable, '-m', 'app'], env=environment, stdout=log, stderr=log)
            try:
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                for _ in range(100):
                    try:
                        with opener.open(base + '/healthz', timeout=1):
                            break
                    except OSError:
                        if process.poll() is not None:
                            raise RuntimeError('Application server failed to start')
                        time.sleep(.1)
                else:
                    raise RuntimeError('Application startup timed out')
                asyncio.run(check(base))
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

if __name__ == '__main__':
    main()
