from datetime import date
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Search(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    model: Literal['m3', 'my', 'ms', 'mx'] = 'm3'
    condition: Literal['used', 'new'] = 'used'
    categories: list[str] = Field(default_factory=lambda: ['LRRWD', 'PRRWD', 'LRAWD'], max_length=20)
    years: list[int] = Field(default_factory=lambda: [2021, 2022, 2023, 2024, 2025], max_length=30)
    paints: list[str] = Field(default_factory=lambda: ['BLACK', 'GREY'], max_length=20)
    price_min: int = Field(25000, ge=0, le=300000)
    price_max: int = Field(45000, ge=0, le=300000)
    odometer_min: int = Field(9000, ge=0, le=1000000)
    odometer_max: int = Field(107000, ge=0, le=1000000)
    zip: str = Field('13220', pattern=r'^[0-9]{5}$')
    latitude: float = Field(43.3957925, ge=-90, le=90)
    longitude: float = Field(5.1744903, ge=-180, le=180)
    range: int = Field(0, ge=0, le=2000)
    @model_validator(mode='after')
    def valid_ranges(self):
        import re
        if self.price_max < self.price_min or self.odometer_max < self.odometer_min:
            raise ValueError('Le maximum doit être supérieur ou égal au minimum.')
        if any(year < 2017 or year > date.today().year + 1 for year in self.years):
            raise ValueError('Année hors de la plage autorisée.')
        for field in ('categories', 'paints'):
            values = sorted(set(x.strip().upper() for x in getattr(self, field)))
            if any(not re.fullmatch(r'[A-Z0-9_-]{1,32}', x) for x in values):
                raise ValueError('Les codes Tesla doivent contenir des lettres, chiffres ou tirets.')
            setattr(self, field, values)
        self.years = sorted(set(self.years))
        return self

    @property
    def signature(self):
        fields = self.model_dump()
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

    def query(self, offset=0):
        options = {}
        for key, values in [('CATEGORY', self.categories), ('Year', self.years), ('PAINT', self.paints)]:
            if values:
                options[key] = values
        return {'query': {
            'model': self.model, 'condition': self.condition, 'options': options,
            'arrangeby': 'Price', 'order': 'asc', 'market': 'FR', 'language': 'fr',
            'super_region': 'north america', 'PaymentType': 'cash',
            'paymentRange': f'{self.price_min},{self.price_max}',
            'Odometer': f'{self.odometer_min},{self.odometer_max}',
            'lng': self.longitude, 'lat': self.latitude, 'zip': self.zip,
            'range': self.range, 'region': 'FR',
        }, 'offset': offset, 'count': 24, 'outsideOffset': 0, 'outsideSearch': False,
            'isFalconDeliverySelectionEnabled': False, 'version': None}


class Password(BaseModel):
    password: str = Field(min_length=12, max_length=256)
