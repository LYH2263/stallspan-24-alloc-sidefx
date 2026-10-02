# StallSpan 市集摊档开间

沿街段一维 First-Fit 开间分配，挡柱不可被摊位跨越，输出分配图与放不下清单。

技术栈：Python 3.12 / FastAPI / SQLAlchemy / PostgreSQL / Vue 3 / TypeScript / Vite

## 启动

```bash
docker compose up --build
```

| 服务 | 地址 |
| --- | --- |
| 前端 | http://localhost:4700 |
| API | http://localhost:9700 |
| API 文档 | http://localhost:9700/docs |
| Postgres | localhost:5448 |

健康检查：`GET http://localhost:9700/api/health`

## 使用说明

1. 在「集日」「街段」确认开市日与可用宽度。
2. 在「摊主」「挡柱」维护需求宽度与障碍位置。
3. 打开「分配图」：
   - **试摆预览**（`POST /api/allocate/preview`）只算不写，运行表与审计表都不变；
   - **确认落库**（`POST /api/allocate/confirm`）在同一数据库事务内写运行行与审计事件（集日、街段、运行主键、时间），审计写失败则整体回滚，运行不留半成功行；即使有摊主放不下也仍是确认成功，不会伪装成拒绝。
   - **裁回种子**（`POST /api/admin/reset`）在同一事务内清空运行/审计并恢复绿仓种子，图面色块同步恢复。
4. 在「放不下」查看最近一次确认中无法安置的摊位（无确认记录时不隐式补写）。

## 开发与测试

```bash
docker compose exec api pytest -q
```
