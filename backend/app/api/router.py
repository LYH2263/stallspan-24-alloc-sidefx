from fastapi import APIRouter
from app.api import admin, allocate, days, pillars, segments, vendors
api_router = APIRouter()

@api_router.get("/health")
def health():
    return {"status": "ok"}

api_router.include_router(days.router)
api_router.include_router(segments.router)
api_router.include_router(vendors.router)
api_router.include_router(pillars.router)
api_router.include_router(allocate.router)
api_router.include_router(admin.router)
