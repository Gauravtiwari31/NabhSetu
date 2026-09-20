from fastapi import APIRouter

from app.api.routes.exports import router as exports_router
from app.api.routes.fares import router as fares_router
from app.api.routes.health import router as health_router
from app.api.routes.index import router as index_router
from app.api.routes.jobs import router as jobs_router
from app.api.routes.methodology import router as methodology_router
from app.api.routes.reference import router as reference_router
from app.api.routes.sources import router as sources_router
from app.api.routes.status import router as status_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(sources_router)
api_router.include_router(jobs_router)
api_router.include_router(fares_router)
api_router.include_router(index_router)
api_router.include_router(methodology_router)
api_router.include_router(exports_router)
api_router.include_router(reference_router)
api_router.include_router(status_router)
