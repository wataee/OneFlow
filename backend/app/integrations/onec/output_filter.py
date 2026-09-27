"""
1C Output Sanitizer and Sensitive Data Filter.

Architectural attribution:
- Concept of pre-LLM output redaction (masking PII, IIN/BIN, IBAN) and
  row count limitation inspired by ashybulakstroy-mcp-1c-bridge
  (https://github.com/ashybulakstroy/ashybulakstroy-mcp-1c-bridge).
  Implemented independently specifically for Kazakhstani financial identifiers.
"""

import re
from typing import Any, Dict, List, Tuple, Union
from app.core.config import settings

# 12-digit Kazakhstani IIN (Individual Identification Number) / BIN (Business Identification Number)
IIN_BIN_REGEX = re.compile(r"\b(\d{4})\d{6}(\d{2})\b")

# Kazakhstani IBAN bank account numbers (KZ + 18 alphanumeric chars = 20 chars total)
IBAN_REGEX = re.compile(r"\b(KZ\d{2})[A-Z0-9]{12}([A-Z0-9]{4})\b", re.IGNORECASE)

# 16-digit payment card numbers
CARD_REGEX = re.compile(r"\b(\d{4})[ -]?\d{4}[ -]?\d{4}[ -]?(\d{4})\b")


def mask_sensitive_string(text: str) -> str:
    """
    Masks Kazakhstani IIN/BIN, IBAN bank accounts, and card numbers within text.
    """
    # Mask IBAN: KZ12************3456
    text = IBAN_REGEX.sub(r"\1************\2", text)
    # Mask Card: 4400-****-****-1234
    text = CARD_REGEX.sub(r"\1-****-****-\2", text)
    # Mask 12-digit IIN/BIN: 9812****1122
    text = IIN_BIN_REGEX.sub(r"\1******\2", text)
    return text


def sanitize_data_node(node: Any) -> Any:
    """
    Recursively traverses dictionaries, lists, and primitives,
    masking sensitive patterns in keys and values.
    """
    if isinstance(node, str):
        return mask_sensitive_string(node)
    elif isinstance(node, dict):
        sanitized = {}
        for k, v in node.items():
            # If key explicitly mentions iin or bin, ensure strict masking
            if isinstance(k, str) and any(term in k.lower() for term in ("iin", "bin", "иин", "бин")) and isinstance(v, str) and len(v) == 12:
                sanitized[k] = f"{v[:4]}******{v[-2:]}"
            else:
                sanitized[k] = sanitize_data_node(v)
        return sanitized
    elif isinstance(node, list):
        return [sanitize_data_node(item) for item in node]
    elif isinstance(node, tuple):
        return tuple(sanitize_data_node(item) for item in node)
    return node


class OneCOutputFilter:
    """
    Applies row limits and sensitive data redaction to 1C OData query results
    before they are dispatched to LLM prompt contexts or API responses.
    """

    def __init__(self, default_max_rows: int = settings.ONEC_OUTPUT_MAX_ROWS):
        self.default_max_rows = default_max_rows

    def filter_result(
        self,
        data: Union[List[Dict[str, Any]], Dict[str, Any]],
        max_rows: int | None = None,
    ) -> Tuple[Any, bool]:
        """
        Limits result rows to prevent LLM context overflow, and masks confidential PII.
        Returns: (sanitized_data, is_truncated)
        """
        limit = max_rows or self.default_max_rows
        is_truncated = False

        if isinstance(data, list):
            if len(data) > limit:
                data = data[:limit]
                is_truncated = True

        sanitized = sanitize_data_node(data)
        return sanitized, is_truncated
