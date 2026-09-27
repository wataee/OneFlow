# Third-Party Notices & Attribution

This project incorporates and references the following open-source software libraries and architectural concepts in compliance with their respective permissive licenses (MIT and Apache 2.0).

---

## 1. onec-odata (External Library Dependency)

* **Repository**: https://github.com/efinskiy/onec-odata
* **Author**: Eugene Finskiy (efinskiy)
* **License**: MIT License
* **Role in Project**: Primary low-level OData v3 client for 1C:Enterprise platform. Utilized as an external Python package dependency (`onec-odata`) in `backend/requirements.txt` and wrapped by `app.integrations.onec.client`.

---

## 2. 1c-odata-mcp (evilbruce666) (Architectural Concept Reference)

* **Repository**: https://github.com/evilbruce666/1c-odata-mcp
* **License**: MIT License
* **Role in Project**: Source of conceptual safety patterns:
  - **Dual-Safety Latch on Writes**: Global `ONEC_READ_ONLY_MODE=true` combined with per-database permission flags (`is_writable`).
  - **1C OData Space Encoding**: Handling of 1C OData quirk where `+` characters in `$filter` clauses are not recognized as spaces (requiring percent-encoding `%20`).
  - **Hierarchical Taxonomy**: Prefixed operation naming convention (`read.analytics.*`, `read.warehouse.*`, `read.system.*`).

---

## 3. pyrfor/onec-odata-mcp (Architectural Concept Reference)

* **Repository**: https://github.com/pyrfor/onec-odata-mcp
* **License**: MIT License
* **Role in Project**: Source of patterns for credential encapsulation and entity reflection between 1C OData entities (Catalogs, Documents, Accumulation Registers) and MCP tool descriptors.

---

## 4. amin-ale/mcp-audit-gateway (Architectural Concept Reference)

* **Repository**: https://github.com/amin-ale/mcp-audit-gateway
* **License**: MIT License
* **Role in Project**: Source of MCP audit proxy concepts:
  - **Dual Telemetry & Audit Correlation**: Binding MCP request IDs to immutable audit log records with latency tracking and status verification.
  - **PII & Sensitive Parameter Masking**: Ensuring token and business identifiers are sanitized before logging.

---

## 5. panossalt/mcp-gateway (Architectural Concept Reference)

* **Repository**: https://github.com/PanosSalt/MCP-Gateway
* **License**: MIT License
* **Role in Project**: Source of enterprise authorization concepts:
  - **Per-Tool RBAC**: Granular role-based access control annotations (`allowed_roles`) on tool definitions, checked both during tool discovery and execution.
  - **Multi-Tenant Token Binding**: Validation of tenant isolation parameters on every MCP invocation.

---

## 6. SidPad03/unified-mcp-gateway (Architectural Concept Reference)

* **Repository**: https://github.com/SidPad03/unified-mcp-gateway
* **License**: Apache 2.0 / MIT License
* **Role in Project**: Aggregated tool registry catalog and unified schema discovery endpoints.

---

## 7. Niraven/mcp-gateway (Architectural Concept Reference)

* **Repository**: https://github.com/Niraven/mcp-gateway
* **License**: MIT License
* **Role in Project**: Source of security firewall mechanisms:
  - **Tool Poisoning Protection**: Deterministic cryptographic SHA-256 fingerprinting (`schema_hash`) of tool schemas and definitions to prevent schema tampering, MITM alteration, and LLM prompt injection drift.

---

## 8. vgtitov/bsl-ai-toolkit (Architectural Concept Reference)

* **Repository**: https://github.com/vgtitov/bsl-ai-toolkit
* **License**: MIT License
* **Role in Project**: Dynamic 1C metadata introspection patterns:
  - **Metadata Discovery Tool**: Safely querying 1C entity schemas (`read.system.get_metadata`) so AI models inspect available catalogs and registers dynamically rather than guessing entity names.

---

## 9. hacker-cb/1c-odata (Architectural Concept Reference)

* **Repository**: https://github.com/hacker-cb/1c-odata
* **License**: MIT License
* **Role in Project**: OData query ergonomics and error parsing:
  - **1C Error Envelope Parsing**: Extracting human-readable Russian/English messages from nested 1C OData XML (`<m:message>`) and JSON (`odata.error.message.value`) payloads in `app.integrations.onec.error_parser`.
  - **Safe Dynamic Catalog Querying**: Bounded entity queries (`read.catalog.query`) with pagination and sensitive field redaction.

---

## 10. modelcontextprotocol/python-sdk (Protocol Reference)

* **Repository**: https://github.com/modelcontextprotocol/python-sdk
* **License**: MIT License
* **Role in Project**: Official Model Context Protocol schema definitions (`Tool`, `CallToolResult`, `TextContent`) and JSON-RPC 2.0 error specifications (`-32700`, `-32600`, `-32601`, `-32602`, `-32603`).

---

## 11. openai/openai-agents-python (Architectural Concept Reference)

* **Repository**: https://github.com/openai/openai-agents-python
* **License**: Apache 2.0 License
* **Role in Project**: Source of Human-in-the-Loop (HITL) and guardrail patterns:
  - **Approval Gates for Tools**: Support for `requires_approval=True` pausing automated tool execution to request human reviewer sign-off via OneFlow's `ReviewTask` FSM, returning `REQUIRES_APPROVAL` with review tracking IDs.
