from __future__ import annotations

from ..storage.cache import CacheManager
from ..storage.database import DatabaseManager
from ..storage.repositories import SettingsRepository
from ..storage.secrets import SecretStore
from .cache import SearchCache
from .service import SearchService
from .sources import CrossrefSource, OpenAlexSource, WosSource
from .transport import HttpxTransport


def build_search_service(database: DatabaseManager) -> SearchService:
    core = database.require_core()
    secrets = SecretStore(core)
    settings = SettingsRepository(core)
    transport = HttpxTransport()
    cache = SearchCache(CacheManager(database.require_cache(), database.paths.cache))
    return SearchService(
        (
            WosSource(secrets.read("wos_api_key"), transport),
            OpenAlexSource(secrets.read("openalex_api_key"), transport),
            CrossrefSource(settings.get("crossref_email"), transport),
        ),
        cache,
    )
