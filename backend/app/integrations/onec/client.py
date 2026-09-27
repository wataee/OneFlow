"""
1C:Enterprise OData Client Wrapper.

Architectural attribution:
- Utilizes the external open-source library `onec-odata` (pip: onec-odata, by Eugene Finskiy, MIT)
  (https://github.com/efinskiy/onec-odata).
- Percent-encoding (%20 instead of +) for 1C OData $filter expressions noted from
  1c-odata-mcp (https://github.com/evilbruce666/1c-odata-mcp).
"""

import asyncio
from typing import Any, Dict, List, Optional
from onec_odata import ODataClient, Query, F
from onec_odata.exceptions import ODataError, ODataConnectionError

from app.core.config import settings


class OneCConfigurationError(Exception):
    pass


class OneCClientWrapper:
    """
    Asynchronous, tenant-aware wrapper around the synchronous onec-odata client.
    Executes blocking HTTP calls via asyncio.to_thread to maintain async ASGI responsiveness.
    """

    def __init__(
        self,
        base_url: str,
        username: Optional[str] = None,
        password: Optional[str] = None,
        timeout: float = 30.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout = timeout
        auth = (username, password) if username and password else None

        self._client = ODataClient(
            base_url=self.base_url,
            auth=auth,
            timeout=timeout,
        )

    @classmethod
    def from_tenant_config(cls, tenant_onec_config: Optional[Dict[str, Any]] = None) -> "OneCClientWrapper":
        """
        Resolves per-organization 1C configuration.
        Falls back to environment settings for local dev/demo.
        """
        cfg = tenant_onec_config or {}
        base_url = cfg.get("base_url") or settings.ONEC_ODATA_URL
        username = cfg.get("username") or settings.ONEC_USERNAME
        password = cfg.get("password") or settings.ONEC_PASSWORD

        if not base_url:
            raise OneCConfigurationError(
                "1C OData base URL is not configured. Provide it in organization settings or set ONEC_ODATA_URL."
            )

        return cls(base_url=base_url, username=username, password=password)

    async def get_metadata(self) -> Dict[str, Any]:
        """Fetches 1C OData metadata document."""
        return await asyncio.to_thread(self._client.metadata)

    async def list_catalog(
        self,
        catalog_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lists records from a 1C Catalog (Справочник) using onec-odata.
        """
        def _call():
            q = Query().top(top).skip(skip)
            if filter_expr is not None:
                q = q.filter(filter_expr)
            entity_set = self._client.catalog(catalog_name)
            res = entity_set.list(query=q)
            return [dict(e) for e in res]

        return await asyncio.to_thread(_call)

    async def list_document(
        self,
        doc_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lists records from a 1C Document (Документ).
        """
        def _call():
            q = Query().top(top).skip(skip)
            if filter_expr is not None:
                q = q.filter(filter_expr)
            entity_set = self._client.document(doc_name)
            res = entity_set.list(query=q)
            return [dict(e) for e in res]

        return await asyncio.to_thread(_call)

    async def list_accumulation_register(
        self,
        register_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """
        Lists records or virtual table data from an Accumulation Register (Регистр накопления).
        """
        def _call():
            q = Query().top(top).skip(skip)
            if filter_expr is not None:
                q = q.filter(filter_expr)
            entity_set = self._client.accumulation_register(register_name)
            res = entity_set.list(query=q)
            return [dict(e) for e in res]

        return await asyncio.to_thread(_call)

    def close(self):
        self._client.close()
