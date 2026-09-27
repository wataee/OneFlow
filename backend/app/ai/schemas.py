from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AIResult(BaseModel):
    data: Dict[str, Any] = Field(description="Structured result dictionary extracted or inferred by AI")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score strictly between 0.0 and 1.0")
    raw_response: Optional[str] = Field(default=None, description="Raw model or provider text output")
    model_used: str = Field(description="Identifier of the model or engine that produced the result")


class AIProcessInput(BaseModel):
    task_type: str = Field(description="Type of task to process")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary task payload")


class AIClassifyInput(BaseModel):
    content: str = Field(description="Textual or serialized content to classify")
    candidate_labels: List[str] = Field(description="Set of candidate labels or categories")


class AIExtractInput(BaseModel):
    content: str = Field(description="Document text or body")
    target_fields: List[str] = Field(description="Fields to extract")


class AIMatchInput(BaseModel):
    source_item: Dict[str, Any] = Field(description="Source object to reconcile")
    candidate_items: List[Dict[str, Any]] = Field(description="List of candidate items to match against")
