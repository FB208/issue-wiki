from sqlalchemy.orm import Session

from app.models import SiteSetting
from app.schemas import SiteBrandingOut, SiteBrandingUpdate

SITE_SETTINGS_ID = 1


def get_site_settings(db: Session) -> SiteBrandingOut:
    setting = db.get(SiteSetting, SITE_SETTINGS_ID)
    if not setting:
        raise RuntimeError("site settings row is missing")
    return SiteBrandingOut(logo_url=setting.logo_url, title=setting.title, subtitle=setting.subtitle)


def save_site_settings(db: Session, payload: SiteBrandingUpdate) -> SiteBrandingOut:
    setting = db.get(SiteSetting, SITE_SETTINGS_ID)
    if not setting:
        raise RuntimeError("site settings row is missing")
    logo_url = (payload.logo_url or "").strip() or None
    setting.logo_url = logo_url
    setting.title = payload.title.strip()
    setting.subtitle = payload.subtitle.strip()
    db.commit()
    return SiteBrandingOut(logo_url=setting.logo_url, title=setting.title, subtitle=setting.subtitle)
