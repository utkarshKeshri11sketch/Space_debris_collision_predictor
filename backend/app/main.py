"""OrbitSentinel API. Run: uvicorn app.main:app --reload --port 8000  (from backend/)."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import warmup
from .routers import ask, cascade, catalog, conjunctions, negotiations


@asynccontextmanager
async def lifespan(_: FastAPI):
    stop = warmup.start()
    yield
    if stop is not None:
        stop.set()


app = FastAPI(title="OrbitSentinel API", version="0.1.0", lifespan=lifespan)

origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-Screening-Complete", "X-Screening-Issues", "X-Screening-As-Of"])
# The full catalog is ~14.5 MB of JSON (~2 MB gzipped); Lambda's buffered limit is 6 MB.
# SSE responses are excluded by Starlette's GZip middleware, so streaming still works.
app.add_middleware(GZipMiddleware, minimum_size=1024)


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    # Frontend reads `message` (or `detail`) from error bodies and shows it to the user.
    first = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(p) for p in first.get("loc", [])[1:])
    message = f"Invalid request: {field} {first.get('msg', '')}".strip() if field else "Invalid request."
    return JSONResponse(status_code=400, content={"message": message})


@app.exception_handler(StarletteHTTPException)
async def http_error(_: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={"message": str(exc.detail)}, headers=exc.headers)


@app.get("/api/health")
def health():
    return {"status": "ok"}


for module in (catalog, conjunctions, negotiations, cascade, ask):
    app.include_router(module.router)
