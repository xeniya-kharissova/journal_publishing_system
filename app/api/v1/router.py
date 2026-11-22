"""API v1 router aggregation."""

from fastapi import APIRouter

from app.api.v1 import admin_users, auth, decisions, journals, manuscripts, reviews, users

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(admin_users.router)
api_router.include_router(journals.router)
api_router.include_router(manuscripts.router)
api_router.include_router(reviews.router)
api_router.include_router(decisions.router)
