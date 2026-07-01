from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.utils import next_sort_order, page_payload, paginate_query
from app.dependencies import get_current_user, get_current_user_optional, get_db
from app.models import Document, DocumentComment, DocumentFolder, Like, LikeTarget, User
from app.schemas import CommentCreate, DocumentCommentOut, DocumentOut, FolderOut, LikeOut, Page

router = APIRouter(tags=["documents"])


def serialize_document(db: Session, doc: Document) -> DocumentOut:
    like_count = db.query(func.count(Like.id)).filter(Like.target_type == LikeTarget.document.value, Like.target_id == doc.id).scalar()
    comment_count = db.query(func.count(DocumentComment.id)).filter(DocumentComment.document_id == doc.id, DocumentComment.deleted_at.is_(None)).scalar()
    return DocumentOut(
        id=doc.id,
        folder_id=doc.folder_id,
        title=doc.title,
        content=doc.content,
        author=doc.author,
        sort_order=doc.sort_order,
        like_count=int(like_count or 0),
        comment_count=int(comment_count or 0),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


@router.get("/navigation")
def navigation(db: Session = Depends(get_db)) -> dict:
    folders = db.query(DocumentFolder).order_by(DocumentFolder.sort_order.asc()).all()
    docs = db.query(Document).order_by(Document.sort_order.asc()).all()
    return {
        "home": {"title": "赞助功能", "path": "/"},
        "folders": [FolderOut.model_validate(item) for item in folders],
        "documents": [serialize_document(db, item) for item in docs],
    }


@router.get("/documents", response_model=Page[DocumentOut])
def list_documents(
    folder_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[DocumentOut]:
    query = db.query(Document)
    if folder_id is not None:
        query = query.filter(Document.folder_id == folder_id)
    docs, total, page, page_size = paginate_query(query.order_by(Document.sort_order.asc()), page, page_size)
    return page_payload([serialize_document(db, item) for item in docs], total, page, page_size)


@router.get("/documents/{document_id}", response_model=DocumentOut)
def get_document(document_id: int, db: Session = Depends(get_db)) -> DocumentOut:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return serialize_document(db, doc)


@router.post("/documents/{document_id}/likes", response_model=LikeOut)
def like_document(
    document_id: int,
    x_guest_id: str | None = Header(default=None),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> LikeOut:
    if user and user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁")
    if not db.get(Document, document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    query = db.query(Like).filter(Like.target_type == LikeTarget.document.value, Like.target_id == document_id)
    if user:
        query = query.filter(Like.user_id == user.id)
    else:
        query = query.filter(Like.guest_id == (x_guest_id or "guest"))
    existing = query.first()
    if not existing:
        db.add(Like(target_type=LikeTarget.document.value, target_id=document_id, user_id=user.id if user else None, guest_id=None if user else (x_guest_id or "guest")))
        db.commit()
    count = db.query(func.count(Like.id)).filter(Like.target_type == LikeTarget.document.value, Like.target_id == document_id).scalar()
    return LikeOut(liked=True, count=int(count or 0))


@router.get("/documents/{document_id}/comments", response_model=Page[DocumentCommentOut])
def list_document_comments(
    document_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[DocumentCommentOut]:
    query = db.query(DocumentComment).filter(DocumentComment.document_id == document_id, DocumentComment.deleted_at.is_(None)).order_by(DocumentComment.created_at.asc())
    comments, total, page, page_size = paginate_query(query, page, page_size)
    items = [
        DocumentCommentOut(
            id=item.id,
            document_id=item.document_id,
            user_id=item.user_id,
            user_nickname=item.user.nickname,
            content=item.content,
            is_confirmed=item.is_confirmed,
            admin_reply=item.admin_reply,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in comments
    ]
    return page_payload(items, total, page, page_size)


@router.post("/documents/{document_id}/comments", response_model=DocumentCommentOut)
def create_document_comment(document_id: int, payload: CommentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentCommentOut:
    if not db.get(Document, document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    comment = DocumentComment(document_id=document_id, user_id=user.id, content=payload.content)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return DocumentCommentOut(
        id=comment.id,
        document_id=comment.document_id,
        user_id=comment.user_id,
        user_nickname=user.nickname,
        content=comment.content,
        is_confirmed=comment.is_confirmed,
        admin_reply=comment.admin_reply,
        created_at=comment.created_at,
        updated_at=comment.updated_at,
    )


@router.get("/folders", response_model=Page[FolderOut])
def list_folders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[FolderOut]:
    items, total, page, page_size = paginate_query(db.query(DocumentFolder).order_by(DocumentFolder.sort_order.asc()), page, page_size)
    return page_payload(items, total, page, page_size)
