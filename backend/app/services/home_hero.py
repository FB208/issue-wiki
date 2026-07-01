from sqlalchemy.orm import Session

from app.models import HomeHero
from app.schemas import HomeHeroOut, HomeHeroUpdate

HOME_HERO_ID = 1


def get_home_hero(db: Session) -> HomeHeroOut:
    hero = db.get(HomeHero, HOME_HERO_ID)
    if not hero:
        raise RuntimeError("home hero content is missing")
    return HomeHeroOut(content=hero.content)


def save_home_hero(db: Session, payload: HomeHeroUpdate) -> HomeHeroOut:
    hero = db.get(HomeHero, HOME_HERO_ID)
    if not hero:
        raise RuntimeError("home hero content is missing")
    hero.content = payload.content
    db.commit()
    return HomeHeroOut(content=hero.content)
