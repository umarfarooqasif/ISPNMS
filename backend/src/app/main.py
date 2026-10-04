from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import admin, auth, billing, collectors, customers, masters
from app.core.config import get_settings
from app.core.db import get_db
from app.services.billing import BillingError

_docs = get_settings().enable_docs
app = FastAPI(
    title="ISP Billing & Collection API",
    version="0.1.0",
    docs_url="/api/docs" if _docs else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if _docs else None,
)

API = "/api/v1"
for module in (auth, admin, masters, collectors, customers, billing):
    app.include_router(module.router, prefix=API)


@app.exception_handler(BillingError)
async def billing_error_handler(_: Request, exc: BillingError):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.get("/health", tags=["ops"])
def health():
    """Liveness: the process is up."""
    return {"status": "ok"}


@app.get("/ready", tags=["ops"])
def ready(db: Session = Depends(get_db)):
    """Readiness: the database answers."""
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(status_code=503, content={"status": "database unavailable"})
    return {"status": "ready"}
