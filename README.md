# Geo 协作平台

Geo 是一个面向内容运营的多平台内容自动化发布平台：运营可以在平台内管理文章、账号、素材与工作流，也可以用 AI 批量生成内容，再由发布 worker 通过浏览器自动化或平台 API 分发到目标账号。遇到验证码、登录态失效或发布前确认时，系统通过 noVNC 提供远程人工接管能力。

> 开发约定、命令与架构细节的唯一事实源是 [`CLAUDE.md`](./CLAUDE.md)；系统化项目文档入口见 [`docs/README.md`](./docs/README.md)。

## 核心能力

- **内容管理**：文章 CRUD、文章分组、Tiptap 富文本、正文 HTML / JSON / 纯文本三份并行结构、附件与分块上传。
- **账号与发布**：多平台账号管理、登录会话、发布任务、发布记录、轮询分发、人工接管、发布前手动确认。
- **AI 生文**：问题池、方案池、方案运行、提示词模板、AI 自动排版、图库智能配图。
- **可视化工作流**：pipeline 节点编排、定时运行、运行快照、运行日志、自动分发。
- **素材与游戏库**：MinIO 图片库、素材分类、游戏库语料、托管抓取、文章配图和游戏引用。
- **MCP / Loop**：面向 Claude Code 的 catalog/action/meta tools，支持生成、分发、视频、周报等 Loop 配方。
- **后台治理**：JWT Cookie 鉴权、admin/operator 角色、审计日志、限流、异常统一 JSON 返回。

## 技术栈

| 层 | 技术 |
| --- | --- |
| 后端 | FastAPI、SQLAlchemy、Alembic、Pydantic Settings |
| 数据库 | MySQL 8（仅支持 MySQL；全文检索使用 ngram FULLTEXT） |
| 前端 | React 19、Vite、TypeScript、Tiptap |
| 自动化 | Playwright、Xvfb、x11vnc、websockify、noVNC |
| AI | LiteLLM、LangGraph、Claude Code MCP Loop |
| 存储 | MinIO、本地 `GEO_DATA_DIR` |
| 部署 | Docker Compose |

## 目录结构

```text
server/          FastAPI 应用、领域模块、MCP tools、worker、测试
web/             React + Vite 前端
docs/            项目文档、设计稿、计划与调研
claude-loops/    Claude Code Loop 配方
scripts/         维护脚本
```

## 本地开发

### 前置依赖

- Python 3.12（推荐使用本项目约定的 conda 环境 `geo_xzpt`）
- pnpm 10.4.0
- MySQL 8
- MinIO（图片库 / 游戏库相关能力需要）
- Docker Compose（生产式联调和发布 worker 建议走容器）

> Windows 本地可以开发文章 CRUD、AI 生文、上传等能力；浏览器自动化发布依赖 Linux 容器内的 Xvfb / x11vnc / websockify / noVNC。

### 安装依赖

```bash
conda activate geo_xzpt
pip install -r requirements.txt -r requirements-dev.txt
pnpm install
```

### 配置环境变量

本地至少需要：

```bash
GEO_JWT_SECRET=<long-random-string>
GEO_DATA_DIR=/path/to/local/data
GEO_DATABASE_URL=mysql+pymysql://geo_user:password@127.0.0.1:3306/geo_dev
```

也可以拆开配置数据库连接：

```bash
GEO_DB_HOST=127.0.0.1
GEO_DB_PORT=3306
GEO_DB_USER=geo_user
GEO_DB_PASS=password
GEO_DB_NAME=geo_dev
```

完整模板见 [`.env.example`](./.env.example)。

### 初始化数据库

```bash
alembic upgrade head
```

### 启动服务

```bash
# 后端 API
uvicorn server.app.main:app --reload --host 127.0.0.1 --port 8000

# 前端开发服务器（必须使用 5173；CORS 仅放行 5173）
pnpm --filter @geo/web dev

# 发布 worker（生产/联调发布任务时使用）
python -m server.worker.executor
```

## Docker Compose 部署

```bash
cp .env.example .env
# 编辑 .env，至少填 MYSQL_*、GEO_JWT_SECRET、GEO_SEED_USERS、MinIO 凭据等
docker compose up -d
docker compose exec app python -m server.scripts.seed_users
```

Compose 会启动 `mysql`、`minio`、`app`、`worker` 和 `nginx`。发布 worker 只能跑单实例，不要使用 `docker compose up --scale worker=N`。

更多上线、备份、回滚和排障说明见 [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) 与 [`docs/project/07-deployment-operations.md`](./docs/project/07-deployment-operations.md)。

## 常用命令

```bash
# 后端质量门禁
ruff check server/
ruff format --check server/
mypy server/app

# 后端测试（MySQL 测试库名必须包含 test）
GEO_TEST_DATABASE_URL=mysql+pymysql://geo_user:password@127.0.0.1:3306/geo_test pytest server/tests/ -q

# 前端质量门禁
pnpm --filter @geo/web lint
pnpm --filter @geo/web typecheck
pnpm --filter @geo/web build
pnpm --filter @geo/web format:check
```

前端当前没有单元测试框架，`typecheck` + `build` 是主要 CI 门禁。

## 关键约定

- **开发约定只维护一份**：新增或修改 AI 编程工具说明时，更新 [`CLAUDE.md`](./CLAUDE.md)，`AGENTS.md` 只保留指针。
- **数据库只支持 MySQL**：不要添加 SQLite 兼容分支；测试数据库名必须包含 `test`。
- **前端开发端口固定 5173**：后端 CORS 只放行 `http://127.0.0.1:5173` 和 `http://localhost:5173`。
- **发布 worker 单实例**：多实例会引入账号登录、pipeline 恢复和浏览器会话冲突。
- **AI Key 启动时不校验**：缺失或错误会在 LiteLLM 调用路径上暴露；Claude Code MCP 生文 Loop 不依赖 `GEO_AI_API_KEY`。
- **敏感凭据可静态加密**：生产建议配置 `GEO_SECRET_KEY` / `GEO_SECRET_KEYS`，并与 DB 备份分开管理。

## 文档入口

- [`CLAUDE.md`](./CLAUDE.md)：开发命令、架构细节、模块约定、Gotchas。
- [`docs/README.md`](./docs/README.md)：文档中心和阅读路径。
- [`docs/project/00-README.md`](./docs/project/00-README.md)：面向产品、评审、开发、运维的完整项目文档集。
- [`docs/AI_GENERATION.md`](./docs/AI_GENERATION.md)：AI 生文模块设计与演进。
- [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md)：部署与运维说明。
- [`CHANGELOG.md`](./CHANGELOG.md)：重要版本变更记录。

## 质量门禁

提交与合并请求的硬门禁包括后端 `ruff check` / `ruff format --check` / `mypy`，以及前端 `typecheck` / `build`。发布请保证部署的 commit 已落在 `main` 上。
