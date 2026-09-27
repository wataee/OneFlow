# Third-Party Notices & Attribution

This project incorporates and references the following open-source software libraries and architectural concepts in compliance with their respective licenses.

---

## 1. onec-odata (External Library Dependency)

* **Repository**: https://github.com/efinskiy/onec-odata
* **Author**: Eugene Finskiy (efinskiy)
* **License**: MIT License
* **Role in Project**: Primary low-level OData v3 client for 1C:Enterprise platform. Utilized as an external Python package dependency (`onec-odata`) in `backend/requirements.txt` and wrapped by `app.integrations.onec.client`.

### MIT License Text:

```text
MIT License

Copyright (c) 2024 Eugene Finskiy

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. ashybulakstroy-mcp-1c-bridge (Architectural Concept Reference)

* **Repository**: https://github.com/ashybulakstroy/ashybulakstroy-mcp-1c-bridge
* **License**: MIT License
* **Role in Project**: Source of architectural concepts for safety, access policies, and data protection:
  - **Risk-Level Taxonomy**: Graduated risk classification (`L0: SAFE_READ` to `L5: DESTRUCTIVE`). Implemented independently in `app.integrations.onec.policy`.
  - **Forbidden Operations Guard**: Pre-execution blocking of raw OData string injections, direct SQL, or arbitrary code execution.
  - **Sensitive Data Masking**: Automatic masking of sensitive personal/business identification identifiers (Kazakhstani IIN and BIN) in `app.integrations.onec.output_filter`.
  - **Immutable Audit Logging**: Reconciled with PostgreSQL/SQLite trigger-protected audit system.

---

## 3. 1c-odata-mcp (Architectural Concept Reference)

* **Repository**: https://github.com/evilbruce666/1c-odata-mcp
* **License**: MIT License
* **Role in Project**: Source of conceptual safety patterns:
  - **Dual-Safety Latch on Writes**: Global `ONEC_READ_ONLY_MODE=true` combined with per-database permission flags (`is_writable`).
  - **1C OData Space Encoding**: Handling of 1C OData quirk where `+` characters in `$filter` clauses are not recognized as spaces (requiring percent-encoding `%20`).
  - **Hierarchical Taxonomy**: Prefixed operation naming convention (`read.analytics.*`, `read.warehouse.*`, `read.system.*`).
