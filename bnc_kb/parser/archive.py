from __future__ import annotations

import io
import zipfile


def read_archive(data: bytes) -> dict[str, str]:
    files: dict[str, str] = {}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            files[info.filename] = zf.read(info.filename).decode("utf-8", errors="replace")
    return files


def find_manifest(files: dict[str, str]) -> str | None:
    for path, content in files.items():
        if path.rsplit("/", 1)[-1] == "kb-manifest.yaml":
            return content
    return None
