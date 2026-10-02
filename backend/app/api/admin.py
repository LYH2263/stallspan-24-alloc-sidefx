"""管理操作编排：仅调用服务层，不允许在此直接删除或重写数据库行。"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.allocation_service import reset_to_seed

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/reset", status_code=204)
def reset(db: Session = Depends(get_db)):
    reset_to_seed(db)
    return None
