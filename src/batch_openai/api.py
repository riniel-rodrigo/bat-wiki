from __future__ import annotations

from fastapi import FastAPI

from .web.routers.batches import router as batches_router
from .web.routers.preview import router as preview_router


app = FastAPI(title="Batch OpenAI API", version="1.0.0")
app.include_router(batches_router)
app.include_router(preview_router)
