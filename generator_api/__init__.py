"""generator_api — Phase 0 Generator API Service.

Accepts POST /kbs/{kb_id}/query, syncs the compiled wiki tree from Blob
Storage, spawns a per-request OpenKB sidecar, proxies the question, and
returns a grounded answer with citations.
"""

from __future__ import annotations

__version__ = "0.1.0"
