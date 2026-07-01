from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.api.utils import next_sort_order, page_payload, paginate_query
from app.dependencies import get_current_user, get_current_user_optional, get_db
from app.models import Document, DocumentComment, DocumentFolder, Like, LikeTarget, User
from app.schemas import CommentCreate, DocumentCommentOut, DocumentOut, FolderOut, LikeOut, Page

router = APIRouter(tags=["documents"])


def document_like_identity_filter(query, user: User | None, guest_id: str | None):
    if user:
        return query.filter(Like.user_id == user.id)
    return query.filter(Like.guest_id == normalize_guest_id(guest_id))


def normalize_guest_id(guest_id: str | None) -> str:
    value = (guest_id or "guest").strip() or "guest"
    return value[:120]


def serialize_document(db: Session, doc: Document, user: User | None = None, guest_id: str | None = None) -> DocumentOut:
    like_count = db.query(func.count(Like.id)).filter(Like.target_type == LikeTarget.document.value, Like.target_id == doc.id).scalar()
    comment_count = db.query(func.count(DocumentComment.id)).filter(DocumentComment.document_id == doc.id, DocumentComment.deleted_at.is_(None)).scalar()
    liked_query = db.query(Like.id).filter(Like.target_type == LikeTarget.document.value, Like.target_id == doc.id)
    liked_by_me = document_like_identity_filter(liked_query, user, guest_id).first() is not None
    return DocumentOut(
        id=doc.id,
        folder_id=doc.folder_id,
        title=doc.title,
        content=doc.content,
        author=doc.author,
        sort_order=doc.sort_order,
        like_count=int(like_count or 0),
        liked_by_me=liked_by_me,
        comment_count=int(comment_count or 0),
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


def serialize_document_comment(item: DocumentComment) -> DocumentCommentOut:
    parent = item.parent if item.parent and item.parent.deleted_at is None else None
    return DocumentCommentOut(
        id=item.id,
        document_id=item.document_id,
        parent_id=item.parent_id,
        parent_user_nickname=parent.user.nickname if parent else None,
        parent_content=parent.content if parent else None,
        user_id=item.user_id,
        user_nickname=item.user.nickname,
        content=item.content,
        admin_reply=item.admin_reply,
        created_at=item.created_at,
        updated_at=item.updated_at,
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
def get_document(
    document_id: int,
    x_guest_id: str | None = Header(default=None, alias="X-Guest-Id"),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> DocumentOut:
    doc = db.get(Document, document_id)
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    return serialize_document(db, doc, user, x_guest_id)


@router.post("/documents/{document_id}/likes", response_model=LikeOut)
def like_document(
    document_id: int,
    x_guest_id: str | None = Header(default=None, alias="X-Guest-Id"),
    user: User | None = Depends(get_current_user_optional),
    db: Session = Depends(get_db),
) -> LikeOut:
    if user and user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被封禁")
    if not db.get(Document, document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    query = db.query(Like).filter(Like.target_type == LikeTarget.document.value, Like.target_id == document_id)
    existing = document_like_identity_filter(query, user, x_guest_id).first()
    if existing is None:
        db.add(Like(
            target_type=LikeTarget.document.value,
            target_id=document_id,
            user_id=user.id if user else None,
            guest_id=None if user else normalize_guest_id(x_guest_id),
        ))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    count = db.query(func.count(Like.id)).filter(Like.target_type == LikeTarget.document.value, Like.target_id == document_id).scalar()
    return LikeOut(liked=True, count=int(count or 0))


@router.get("/documents/{document_id}/comments", response_model=Page[DocumentCommentOut])
def list_document_comments(
    document_id: int,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[DocumentCommentOut]:
    query = (
        db.query(DocumentComment)
        .options(
            joinedload(DocumentComment.user),
            joinedload(DocumentComment.parent).joinedload(DocumentComment.user),
        )
        .filter(DocumentComment.document_id == document_id, DocumentComment.deleted_at.is_(None))
        .order_by(DocumentComment.created_at.asc())
    )
    comments, total, page, page_size = paginate_query(query, page, page_size)
    items = [serialize_document_comment(item) for item in comments]
    return page_payload(items, total, page, page_size)


@router.post("/documents/{document_id}/comments", response_model=DocumentCommentOut)
def create_document_comment(document_id: int, payload: CommentCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> DocumentCommentOut:
    if not db.get(Document, document_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="文档不存在")
    parent = None
    if payload.parent_id:
        parent = db.get(DocumentComment, payload.parent_id)
        if not parent or parent.document_id != document_id or parent.deleted_at is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="回复的评论不存在")
    comment = DocumentComment(
        document_id=document_id,
        parent_id=parent.id if parent else None,
        user_id=user.id,
        content=payload.content,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return serialize_document_comment(comment)


@router.get("/folders", response_model=Page[FolderOut])
def list_folders(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
) -> Page[FolderOut]:
    items, total, page, page_size = paginate_query(db.query(DocumentFolder).order_by(DocumentFolder.sort_order.asc()), page, page_size)
    return page_payload(items, total, page, page_size)
