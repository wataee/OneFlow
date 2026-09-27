"""
1C:Enterprise OData Error Envelope Parser & Sanitizer.

Architectural attribution:
- Inspired by error handling patterns in hacker-cb/1c-odata (MIT) and efinskiy/onec-odata (MIT).
- Parses nested 1C OData XML (<m:message>) and JSON (odata.error.message.value) envelopes
  into clean, actionable human-readable messages for AI agents and users, stripping internal
  stack traces and credentials.
"""

import json
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional


def parse_onec_error_response(response_content: Any, status_code: Optional[int] = None) -> str:
    """
    Extracts a concise, human-readable error description from 1C OData error payloads.
    Supports both JSON and XML OData v3 error envelopes.
    """
    if not response_content:
        return f"1C OData service returned HTTP {status_code or 'error'} with empty response."

    text = str(response_content).strip()

    # 1. Attempt JSON parsing
    if (text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]")):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                # Standard OData v3 JSON error: {"odata.error": {"code": "...", "message": {"lang": "ru", "value": "..."}}}
                odata_err = data.get("odata.error") or data.get("error")
                if isinstance(odata_err, dict):
                    msg_obj = odata_err.get("message")
                    if isinstance(msg_obj, dict):
                        val = msg_obj.get("value")
                        if val:
                            return str(val).strip()
                    elif isinstance(msg_obj, str) and msg_obj:
                        return msg_obj.strip()

                    code = odata_err.get("code")
                    if code:
                        return f"1C OData Error {code}"

                # Alternative JSON structures
                if "detail" in data:
                    return str(data["detail"]).strip()
                if "message" in data:
                    return str(data["message"]).strip()
        except Exception:
            pass

    # 2. Attempt XML parsing
    if "<" in text and ">" in text:
        try:
            # Strip XML declaration if present and parse
            root = ET.fromstring(text)
            # Find message element regardless of namespace
            for elem in root.iter():
                tag_name = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
                if tag_name.lower() == "message" and elem.text:
                    clean_msg = elem.text.strip()
                    if clean_msg:
                        return clean_msg
        except Exception:
            # Fallback regex search for <m:message> or <message>
            xml_match = re.search(r"<(?:[a-zA-Z0-9_]+:)?message[^>]*>(.*?)</(?:[a-zA-Z0-9_]+:)?message>", text, re.DOTALL | re.IGNORECASE)
            if xml_match:
                extracted = xml_match.group(1).strip()
                if extracted:
                    return extracted

    # 3. Fallback: Clean string up to 200 chars
    cleaned = re.sub(r"<[^>]+>", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if len(cleaned) > 200:
        cleaned = cleaned[:197] + "..."
    return cleaned or f"1C OData communication failed (HTTP {status_code or 'error'})."
