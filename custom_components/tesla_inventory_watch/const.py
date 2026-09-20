"""Constants for Tesla Inventory Watch."""

from homeassistant.const import Platform

DOMAIN = "tesla_inventory_watch"
PLATFORMS = [Platform.SENSOR, Platform.BUTTON]

CONF_MODEL = "model"
CONF_CONDITION = "condition"
CONF_CATEGORIES = "categories"
CONF_YEARS = "years"
CONF_PAINTS = "paints"
CONF_PRICE_MIN = "price_min"
CONF_PRICE_MAX = "price_max"
CONF_ODOMETER_MIN = "odometer_min"
CONF_ODOMETER_MAX = "odometer_max"
CONF_ZIP = "zip"
CONF_RANGE = "range"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_INTERVAL = "interval_minutes"
CONF_NOTIFY_ENABLED = "notify_enabled"
CONF_NOTIFY_SERVICE = "notify_service"
CONF_SORT = "sort"
CONF_ORDER = "order"

DEFAULT_MODEL = "m3"
DEFAULT_CONDITION = "used"
DEFAULT_CATEGORIES = ["LRRWD", "PRRWD", "LRAWD"]
DEFAULT_YEARS = ["2021", "2022", "2023", "2024", "2025"]
DEFAULT_PAINTS = ["BLACK", "GREY"]
DEFAULT_PRICE_MIN = 25000
DEFAULT_PRICE_MAX = 45000
DEFAULT_ODOMETER_MIN = 9000
DEFAULT_ODOMETER_MAX = 107000
DEFAULT_ZIP = "13220"
DEFAULT_RANGE = 0
DEFAULT_LATITUDE = 43.3957925
DEFAULT_LONGITUDE = 5.1744903
DEFAULT_INTERVAL = 5
DEFAULT_NOTIFY_ENABLED = False
DEFAULT_NOTIFY_SERVICE = ""
DEFAULT_SORT = "Price"
DEFAULT_ORDER = "asc"

MIN_INTERVAL = 2
MAX_INTERVAL = 1440

TESLA_API = "https://www.tesla.com/inventory/api/v4/inventory-results"
TESLA_INVENTORY_BASE = "https://www.tesla.com/fr_FR/inventory"

EVENT_NEW_VEHICLE = f"{DOMAIN}_new_vehicle"
STORAGE_VERSION = 1
