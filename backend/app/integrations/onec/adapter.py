"""
1C:Enterprise Adapter Abstraction Layer.
Decouples application services and tool executors from specific transport protocols
(OData v3, Mock, future gRPC or Native COM adapters).
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from onec_odata import F

from app.integrations.onec.client import OneCClientWrapper


class OneCAdapter(ABC):
    """
    Abstract contract for 1C:Enterprise data adapters.
    Provides uniform interface for metadata, catalogs, documents, and accumulation registers.
    """

    @property
    @abstractmethod
    def is_mock(self) -> bool:
        """True if the adapter operates in synthetic/mock mode."""
        pass

    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """Checks connection availability and basic system metadata."""
        pass

    @abstractmethod
    async def get_metadata(self) -> Dict[str, Any]:
        """Retrieves 1C OData metadata document."""
        pass

    @abstractmethod
    async def list_catalog(
        self,
        catalog_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Lists records from a 1C Catalog (Справочник)."""
        pass

    @abstractmethod
    async def list_document(
        self,
        doc_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Lists records from a 1C Document (Документ)."""
        pass

    @abstractmethod
    async def list_accumulation_register(
        self,
        register_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        """Lists records or balances from an Accumulation Register (Регистр накопления)."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Closes any underlying network connections/sessions."""
        pass


class ODataAdapter(OneCAdapter):
    """
    Real 1C OData v3 adapter wrapping OneCClientWrapper.
    """

    def __init__(self, client: OneCClientWrapper):
        self._client = client

    @property
    def is_mock(self) -> bool:
        return False

    async def health_check(self) -> Dict[str, Any]:
        meta = await self._client.get_metadata()
        return {"status": "connected", "metadata_received": bool(meta)}

    async def get_metadata(self) -> Dict[str, Any]:
        return await self._client.get_metadata()

    async def list_catalog(
        self,
        catalog_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        return await self._client.list_catalog(catalog_name, top=top, skip=skip, filter_expr=filter_expr)

    async def list_document(
        self,
        doc_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        return await self._client.list_document(doc_name, top=top, skip=skip, filter_expr=filter_expr)

    async def list_accumulation_register(
        self,
        register_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        return await self._client.list_accumulation_register(
            register_name, top=top, skip=skip, filter_expr=filter_expr
        )

    async def close(self) -> None:
        self._client.close()


class MockAdapter(OneCAdapter):
    """
    Deterministic mock adapter providing realistic 1C:Enterprise Kazakhstan accounting responses
    without connecting to a live 1C infobase.
    """

    @property
    def is_mock(self) -> bool:
        return True

    async def health_check(self) -> Dict[str, Any]:
        return {
            "status": "connected",
            "infobase_version": "8.3.24.1548",
            "configuration": "Бухгалтерия для Казахстана, ред. 3.0",
            "latency_ms": 14.2,
        }

    async def get_metadata(self) -> Dict[str, Any]:
        return {
            "version": "1.0",
            "schema": "StandardODATA",
            "entities": [
                "Catalog_Контрагенты",
                "Document_ПлатежноеПоручениеИсходящее",
                "AccumulationRegister_ТоварыНаСкладах",
                "AccumulationRegister_ВзаиморасчетыСКонтрагентами",
            ],
        }

    async def list_catalog(
        self,
        catalog_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        catalogs = [
            {"Ref_Key": "00000000-0000-0000-0001-000000000101", "Description": "ТОО Сарыарка Энерджи", "Code": "000001"},
            {"Ref_Key": "00000000-0000-0000-0001-000000000102", "Description": "ТОО Базис Металл", "Code": "000002"},
        ]
        return catalogs[skip : skip + top]

    async def list_document(
        self,
        doc_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        # Deterministic mock reflecting typical KZ accounting unposted drafts
        docs = [
            {
                "Ref_Key": "00000000-0000-0000-0001-000000000001",
                "Number": "KZ-000142",
                "Date": "2026-09-25T14:30:00",
                "Posted": False,
                "СуммаДокумента": 1250000,
                "Контрагент": "ТОО Сарыарка Энерджи",
                "Контрагент_БИН": "080140012345",  # Will be masked by output_filter
                "НазначениеПлатежа": "Оплата по счету №441/26 за электроэнергию",
            },
            {
                "Ref_Key": "00000000-0000-0000-0001-000000000002",
                "Number": "KZ-000143",
                "Date": "2026-09-26T10:15:00",
                "Posted": False,
                "СуммаДокумента": 480000,
                "Контрагент": "ИП Касымов Д.А.",
                "Контрагент_ИИН": "850412350789",  # Will be masked by output_filter
                "НазначениеПлатежа": "Транспортные услуги согласно акту",
            },
        ]
        return docs[skip : skip + top]

    async def list_accumulation_register(
        self,
        register_name: str,
        top: int = 50,
        skip: int = 0,
        filter_expr: Optional[Any] = None,
    ) -> List[Dict[str, Any]]:
        if "Взаиморасчеты" in register_name:
            debtors = [
                {
                    "counterparty": "ТОО Базис Металл",
                    "bin": "981240001122",  # Will be masked
                    "debt_amount_kzt": 3450000.0,
                    "overdue_days": 18,
                    "contract": "Договор поставки № 12/25",
                    "iban": "KZ449988112233445566",  # Will be masked
                },
                {
                    "counterparty": "АО Астана Финанс Групп",
                    "bin": "050340008899",  # Will be masked
                    "debt_amount_kzt": 890000.50,
                    "overdue_days": 4,
                    "contract": "Договор лизинга № 88-Л",
                    "iban": "KZ120011223344556677",  # Will be masked
                },
            ]
            return debtors[skip : skip + top]

        # Warehouse balances
        inventory = [
            {
                "sku": "ITEM-KZ-001",
                "name": "Кабель силовой ВВГнг 3x2.5",
                "warehouse": "Центральный склад Алматы",
                "quantity": 1450.0,
                "unit": "м",
                "reserved": 200.0,
                "available": 1250.0,
            },
            {
                "sku": "ITEM-KZ-002",
                "name": "Автоматический выключатель 16A",
                "warehouse": "Центральный склад Алматы",
                "quantity": 84.0,
                "unit": "шт",
                "reserved": 0.0,
                "available": 84.0,
            },
        ]
        return inventory[skip : skip + top]

    async def close(self) -> None:
        pass
