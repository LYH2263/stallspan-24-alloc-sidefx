"""合同测试夹具：与 Postgres 绿仓隔离的独立 SQLite 库 + FastAPI TestClient。"""
from __future__ import annotations

import os

# 必须在导入 app.* 之前：app.database 导入时即按 DATABASE_URL 建引擎。
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.services.seed import seed_data


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _record):
        # 打开外键约束，让“互指”可由数据库与帮手双重校验。
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    maker = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = maker()
    seed_data(session)  # 绿仓种子基线，不预设任何运行/审计行
    session.commit()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture()
def client(db) -> TestClient:
    def _override_get_db():
        try:
            yield db
        finally:
            # 不关闭：夹具持有同一会话工厂连接；事务状态由服务层负责。
            pass

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
