"""Inbound webhook routes.

The n8n publish-result callback (POST /publish-result) and its shared-secret/
HMAC verification were removed on 2026-08-22 along with the n8n publishing
hop: every channel now publishes natively from the backend
(``app.services.publishers``) and results are written directly by
``publish_service.record_publish_result`` — no external callback exists.

The router stays registered (see ``app/api/router.py``) as the mount point
for any future inbound webhooks; the ``webhook_events`` dedup table also
remains (harmless, migration already shipped).
"""

from fastapi import APIRouter

router = APIRouter()
