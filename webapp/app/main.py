import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from pydantic import BaseModel
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .db import Store
from .models import Password, Search
from .service import Service
from .tesla import InventoryError, import_vehicles

STATIC = Path(__file__).parent / 'static'


class Enabled(BaseModel):
    enabled: bool


class Import(BaseModel):
    data: dict


def create_app(settings=None, collector=None):
    settings = settings or Settings.from_env()
    store = Store(settings.data_dir)
    service = Service(store, settings, collector)

    @asynccontextmanager
    async def lifespan(app):
        # One browser worker per data directory, even with accidental --workers 2.
        lock = FileLock(settings.data_dir / 'application.lock')
        lock.acquire(timeout=0)
        await asyncio.to_thread(store.recover)
        worker = asyncio.create_task(service.run()) if settings.scheduler else None
        try:
            yield
        finally:
            if worker:
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
            await service.close()
            lock.release()

    app = FastAPI(title='Tesla Inventory Watch', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.service = store, service
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))

    @app.middleware('http')
    async def secure_requests(request, call_next):
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            expected = settings.public_url or str(request.base_url).rstrip('/')
            origin = request.headers.get('origin')
            if request.headers.get('x-requested-with') != 'TeslaInventoryWatch' or (origin and origin != expected):
                return JSONResponse({'detail':'Origine de requête refusée.'}, status_code=403)
            try:
                if int(request.headers.get('content-length', '0')) > 2 * 1024 * 1024:
                    return JSONResponse({'detail':'Fichier trop volumineux (2 Mo maximum).'}, status_code=413)
            except ValueError:
                return JSONResponse({'detail':'Requête invalide.'}, status_code=400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if request.url.path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        return response

    async def authorized(request: Request):
        if not await asyncio.to_thread(store.authenticated, request.cookies.get('session')):
            raise HTTPException(401, 'Connectez-vous pour accéder à votre surveillance.')

    def session_cookie(response, token):
        response.set_cookie('session', token, httponly=True, secure=settings.cookie_secure,
                            samesite='strict', max_age=30 * 86400, path='/')

    @app.get('/healthz')
    async def health():
        return {'status':'ok'}

    @app.get('/api/session')
    async def session(request: Request):
        return {'authenticated':await asyncio.to_thread(store.authenticated, request.cookies.get('session')),
                'needs_setup':await asyncio.to_thread(store.needs_setup)}

    @app.post('/api/setup')
    async def setup(body: Password, response: Response):
        try:
            await asyncio.to_thread(store.setup_password, body.password)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        session_cookie(response, await asyncio.to_thread(store.new_session))
        return {'ok':True}

    @app.post('/api/login')
    async def login(body: Password, request: Request, response: Response):
        try:
            valid = await asyncio.to_thread(store.login, body.password, request.client.host if request.client else 'unknown')
        except ValueError as error:
            raise HTTPException(429, str(error)) from error
        if not valid:
            raise HTTPException(401, 'Mot de passe incorrect.')
        session_cookie(response, await asyncio.to_thread(store.new_session))
        return {'ok':True}

    @app.post('/api/logout', dependencies=[Depends(authorized)])
    async def logout(request: Request, response: Response):
        await asyncio.to_thread(store.logout, request.cookies.get('session', ''))
        response.delete_cookie('session', path='/')
        return {'ok':True}

    @app.get('/api/dashboard', dependencies=[Depends(authorized)])
    async def dashboard():
        return await asyncio.to_thread(store.snapshot)

    @app.put('/api/config', dependencies=[Depends(authorized)])
    async def configure(search: Search):
        changed = await asyncio.to_thread(store.configure, search)
        return {'ok':True, 'baseline_reset':changed}

    @app.post('/api/enabled', dependencies=[Depends(authorized)])
    async def enable(body: Enabled):
        await asyncio.to_thread(store.enable, body.enabled)
        service.wake.set()
        return {'ok':True}

    @app.post('/api/check', dependencies=[Depends(authorized)])
    async def check():
        if not await service.start_check(manual=True):
            state = (await asyncio.to_thread(store.snapshot))['state']
            raise HTTPException(409, {'message':'Le prochain contrôle n’est pas encore autorisé, ou un contrôle est en cours.', 'next_check':state['next_check']})
        return JSONResponse({'ok':True}, status_code=202)

    @app.post('/api/import', dependencies=[Depends(authorized)])
    async def import_snapshot(body: Import):
        try:
            search = await asyncio.to_thread(store.search)
            vehicles = import_vehicles(body.data, search)
            count = await asyncio.to_thread(store.import_snapshot, vehicles)
        except (ValueError, InventoryError) as error:
            raise HTTPException(422, str(error)) from error
        service.wake.set()
        return {'ok':True, 'count':len(vehicles), 'new':count}

    @app.post('/api/events/read', dependencies=[Depends(authorized)])
    async def read_events():
        await asyncio.to_thread(store.mark_read)
        return {'ok':True}

    @app.get('/')
    async def index():
        return FileResponse(STATIC / 'index.html')

    app.mount('/static', StaticFiles(directory=STATIC), name='static')
    return app
