from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.schemas import HomeHeroOut
from app.services.home_hero import get_home_hero

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/home-hero", response_model=HomeHeroOut)
def read_home_hero(db: Session = Depends(get_db)) -> HomeHeroOut:
    return get_home_hero(db)
