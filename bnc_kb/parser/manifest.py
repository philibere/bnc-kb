from __future__ import annotations

import yaml

from bnc_kb.models import IngestManifest


def parse_manifest(raw: bytes) -> IngestManifest:
    data = yaml.safe_load(raw) or {}
    return IngestManifest(**data)
