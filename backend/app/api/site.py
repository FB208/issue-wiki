from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.config import settings
from app.dependencies import get_db
from app.schemas import HomeHeroOut, SiteBrandingOut
from app.services.home_hero import get_home_hero
from app.services.site_settings import get_site_settings

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/home-hero", response_model=HomeHeroOut)
def read_home_hero(db: Session = Depends(get_db)) -> HomeHeroOut:
    return get_home_hero(db)


@router.get("/branding", response_model=SiteBrandingOut)
def read_branding(db: Session = Depends(get_db)) -> SiteBrandingOut:
    branding = get_site_settings(db)
    if settings.github_repo:
        branding.served_project_url = f"https://github.com/{settings.github_repo}"
        name = settings.github_project_name.strip()
        branding.served_project_name = name or settings.github_repo.split("/")[-1]
    return branding
