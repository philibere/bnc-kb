from __future__ import annotations

from fastapi import FastAPI

from bnc_kb.api import add, admin, search


def create_app() -> FastAPI:
    app = FastAPI(title="bnc-kb", version="0.1.0")
    app.include_router(add.router)
    app.include_router(search.router)
    app.include_router(admin.router)
    return app


app = create_app()
