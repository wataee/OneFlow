from abc import ABC, abstractmethod
from app.ai.schemas import (
    AIClassifyInput,
    AIExtractInput,
    AIMatchInput,
    AIProcessInput,
    AIResult,
)


class AIProvider(ABC):
    """
    Abstract contract for AI processing providers.
    All methods have explicitly typed Pydantic signatures without loose kwargs.
    """

    @abstractmethod
    async def process(self, input_data: AIProcessInput) -> AIResult:
        """Universal pipeline processing for a task payload."""
        pass

    @abstractmethod
    async def classify(self, input_data: AIClassifyInput) -> AIResult:
        """Classifies content into candidate categories."""
        pass

    @abstractmethod
    async def extract(self, input_data: AIExtractInput) -> AIResult:
        """Extracts structured schema fields from document content."""
        pass

    @abstractmethod
    async def match(self, input_data: AIMatchInput) -> AIResult:
        """Finds matching counterparts between source and candidate items."""
        pass
