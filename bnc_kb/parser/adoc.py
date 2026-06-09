from __future__ import annotations

import re

# AsciiDoc document attributes look like `:name: value` at line start.
_ATTR_RE = re.compile(r"^:([\w-]+):[ \t]*(.*)$", re.MULTILINE)


def extract_adoc_attrs(text: str) -> dict[str, str]:
    return {m.group(1): m.group(2).strip() for m in _ATTR_RE.finditer(text)}
