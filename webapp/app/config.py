from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    allowed_hosts: tuple[str, ...] = ('localhost', '127.0.0.1', '[::1]')
    public_url: str = ''
    cookie_secure: bool = False
    chromium: str = '/usr/bin/chromium'
    headless: bool = True
    scheduler: bool = True

    @classmethod
    def from_env(cls):
        return cls(
            data_dir=Path(os.getenv('DATA_DIR', './data')).resolve(),
            allowed_hosts=tuple(x.strip() for x in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1,[::1]').split(',') if x.strip()),
            public_url=os.getenv('PUBLIC_URL', '').rstrip('/'),
            cookie_secure=os.getenv('COOKIE_SECURE', '0') == '1',
            chromium=os.getenv('CHROMIUM_EXECUTABLE', '/usr/bin/chromium'),
            headless=os.getenv('BROWSER_HEADLESS', '1') != '0',
        )
