from fastapi import APIRouter, Depends, UploadFile
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.models import UploadFileRecord, User
from app.schemas import UploadOut
from app.services.storage import upload_to_rustfs, validate_upload_file

router = APIRouter(prefix="/uploads", tags=["uploads"])


@router.post("", response_model=UploadOut)
async def upload_file(file: UploadFile, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> UploadFileRecord:
    data = await file.read()
    suffix = validate_upload_file(file.filename or "upload", file.content_type or "", len(data))
    object_key, url = upload_to_rustfs(file, data, suffix)
    record = UploadFileRecord(
        original_filename=file.filename or "upload",
        file_type=suffix.lstrip("."),
        mime_type=file.content_type or "application/octet-stream",
        file_size=len(data),
        object_key=object_key,
        url=url,
        uploaded_by=user.id,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record
