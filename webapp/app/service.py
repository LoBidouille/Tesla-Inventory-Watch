import asyncio
import logging

from .tesla import BrowserCollector, InventoryError

_LOGGER = logging.getLogger(__name__)


class Service:
    def __init__(self, store, settings, collector=None):
        self.store, self.settings = store, settings
        self.collector = collector or BrowserCollector(settings)
        self.tasks = set()
        self.wake = asyncio.Event()

    async def start_check(self, manual=False):
        claim = await asyncio.to_thread(self.store.claim, manual)
        if claim is None:
            return False
        task = asyncio.create_task(self._collect(claim))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return True

    async def _collect(self, claim):
        try:
            vehicles = await self.collector.collect(claim['config'])
            await asyncio.to_thread(self.store.finish, claim, vehicles)
        except InventoryError as error:
            await asyncio.to_thread(self.store.fail, claim, str(error), error.retry_after)
        except asyncio.CancelledError:
            # The persisted reservation survives shutdown; recover() explains it next boot.
            raise
        except Exception:
            _LOGGER.exception('Inventory check failed')
            await asyncio.to_thread(self.store.fail, claim, 'Erreur interne pendant le contrôle. Consultez les journaux du serveur.')
        finally:
            self.wake.set()

    async def run(self):
        while True:
            self.wake.clear()
            try:
                await self.start_check()
            except Exception:
                _LOGGER.exception('Background worker failed')
            try:
                await asyncio.wait_for(self.wake.wait(), timeout=30)
            except TimeoutError:
                pass

    async def close(self):
        tasks = tuple(self.tasks)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
