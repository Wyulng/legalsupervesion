# 民事判决书智能监督模型

An AI-assisted review system for civil judgments. It uses four focused review models to identify common issues in notice fees, litigation fees, delayed-performance interest, and contract termination timing.

面向民事判决书的 AI 辅助审查系统，通过文件解析、候选过滤和四个专项模型，帮助检察监督人员快速定位常见裁判问题。系统结果仅用于检察监督参考，不替代人工审查、法律判断或正式法律意见。

## 项目简介

本项目适合在本地或受控内网中运行。用户上传判决书后，系统会提取文本并并行调用四个审查模型，返回问题判断、风险等级、理由和建议。批量任务支持 SSE 实时进度推送，同时保留轮询接口作为兜底方案。

项目不提供公共在线实例。判决书、API Key 和审查历史可能包含敏感信息，请在可信网络和受控环境中部署。

## 核心能力

| 模型 | 审查主题 | 识别重点 |
| --- | --- | --- |
| M1 | 公告费 | 法院公告送达但裁判文书未处理公告费 |
| M3 | 合同解除时间 | 合同解除时间、解除理由与法律要件是否匹配 |
| M5 | 诉讼费 | 案件受理费、申请费是否被错误判给胜诉方 |
| M10 | 加倍利息 | 金钱给付义务是否遗漏迟延履行期间的加倍利息表述 |

其他能力：

- 支持 `.doc`、`.docx`、`.pdf` 和 `.txt` 文件，单文件最大 100 MB。
- 统一通过批量任务接口审查一个或多个文件。
- SSE 实时进度推送，连接异常时自动回退到任务轮询。
- 结果表格、详情展开、CSV 下载和历史任务管理。
- Docker Compose 一键启动，前端无需构建链。
- JSON 文件持久化任务状态、历史记录和结果文件。

## 处理流程

```text
上传判决书
    ↓
文件解析与文本清洗
    ↓
正则候选过滤，跳过明显不相关文本
    ↓
M1 / M3 / M5 / M10 并行审查
    ↓
结构化结果校验与风险归类
    ↓
SSE 或轮询返回进度
    ↓
历史记录持久化并生成 CSV
```

## 技术架构

```text
浏览器
   │ 同源请求
   ▼
Nginx 静态前端 ── /review/* ──> FastAPI 后端
                                  ├─ 文档解析
                                  ├─ 候选过滤
                                  ├─ 四模型并行调用
                                  └─ 任务 / 历史 / CSV 存储
                                             │
                                             ▼
                                  OpenAI-compatible LLM API
```

| 层级 | 技术 |
| --- | --- |
| 前端 | 单页 HTML、原生 JavaScript、CSS、Nginx |
| 后端 | Python 3.11、FastAPI、Uvicorn |
| 文档解析 | PyMuPDF、python-docx、antiword |
| 模型调用 | OpenAI Python SDK，兼容 OpenAI 格式的接口 |
| 数据存储 | 本地 JSON、CSV，Docker 挂载 `data/` |
| 部署 | Docker、Docker Compose |

## 快速开始

### 环境要求

- Docker Desktop 或 Docker Engine，包含 Compose 插件。
- 可用的 OpenAI-compatible LLM API Key。
- 至少能为后端依赖和模型调用预留足够的运行内存。

### Docker Compose 启动

1. 复制环境变量模板：

   ```bash
   cp .env.example .env
   ```

   PowerShell：

   ```powershell
   Copy-Item .env.example .env
   ```

2. 编辑 `.env`，至少填写：

   ```dotenv
   OPENAI_API_KEY=your_api_key
   OPENAI_BASE_URL=https://your-openai-compatible-endpoint/v1
   MODEL_NAME=your_model_name
   ```

3. 构建并启动：

   ```bash
   docker compose up -d --build
   ```

4. 检查后端健康状态：

   ```bash
   curl http://localhost:8000/health
   ```

   正常情况下返回：

   ```json
   {"status":"ok"}
   ```

5. 在本机打开前端：<http://localhost:8080>

停止服务：

```bash
docker compose down
```

`data/` 通过卷挂载保存，停止容器不会自动删除审查历史和 CSV 结果。

## 本地后端开发

该方式用于后端调试；需要完整前端代理和 SSE 配置时，优先使用 Docker Compose。

```bash
cd backend
pip install -r requirements.txt
python run.py
```

Python 语法检查：

```bash
python -m compileall -q backend/app
```

运行后端回归测试：

```bash
cd backend
python -m unittest discover -s tests -v
```

## 配置说明

配置模板位于 `.env.example`。不要提交真实 `.env`、API Key 或判决书文件。

| 变量 | 必填 | 说明 |
| --- | --- | --- |
| `OPENAI_API_KEY` | 是 | LLM 服务 API Key |
| `OPENAI_BASE_URL` | 是 | OpenAI-compatible 接口地址 |
| `MODEL_NAME` | 是 | 使用的模型名称 |
| `LLM_MAX_CONCURRENT` | 否 | 并发模型调用数，默认 `2` |
| `DEBUG_LOG` | 否 | 是否通过 SSE 推送调试日志，默认 `false` |
| `CORS_ORIGINS` | 否 | 允许的来源列表，多个来源用逗号分隔；默认 `*`，分离部署时应收紧 |

## API 参考

### 系统与审查

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 返回服务健康状态 |
| `POST` | `/review/batch` | 上传一个或多个文件，返回 `task_id` |
| `GET` | `/review/batch/{task_id}` | 查询批量任务状态和已完成结果 |
| `GET` | `/review/stream/{task_id}` | 通过 SSE 推送任务状态和进度 |
| `GET` | `/review/download/{filename}` | 下载生成的 CSV 结果 |

### 历史记录

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/review/history?limit=50&offset=0` | 分页获取历史任务列表 |
| `GET` | `/review/history/{task_id}` | 获取历史任务详情和统计信息 |
| `DELETE` | `/review/history/{task_id}` | 删除单条历史记录及其 CSV |
| `DELETE` | `/review/history` | 清除全部历史记录及其 CSV |

批量任务状态依次为 `pending`、`processing`、`completed` 或 `failed`。任务不存在、过期或任务 ID 不合法时，接口会返回相应的 4xx 错误。

## 数据与持久化

| 目录 | 内容 | 生命周期 |
| --- | --- | --- |
| `data/uploads/` | 临时上传文件 | 审查完成或失败后清理 |
| `data/tasks/` | 进行中的任务状态 | 旧任务文件会在启动清理阶段处理 |
| `data/history/` | 已完成或失败的历史任务 JSON | 持久保存，支持界面查看和删除 |
| `data/results/` | CSV 审查结果 | 与历史记录关联保存 |

这些目录被 `.gitignore` 和 Docker ignore 规则排除，不应提交到 Git。生产环境应将 `data/` 纳入备份和访问控制范围。

## 目录结构

```text
legalsupervesion/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI 路由、任务处理和审查流程
│   │   ├── config.py            # 项目根目录、数据目录和环境变量
│   │   ├── models/              # Pydantic 数据模型
│   │   ├── services/            # 解析、LLM 调用、过滤和任务存储
│   ├── dockerfile               # 后端镜像定义
│   ├── requirements.txt
│   └── run.py                   # 本地后端入口
├── frontend/
│   ├── index.html               # 原生 HTML/JS 单页前端
│   └── nginx.conf               # 静态文件和 API/SSE 反向代理
├── data/                        # 运行时数据，不提交
├── docker-compose.yml
├── .env.example
├── LICENSE
└── README.md
```

## 限制与安全

- 模型输出可能存在遗漏、误报或事实错误，必须由专业人员复核。
- 上传文件可能包含个人信息、案件信息或其他敏感内容，应使用受控存储和网络策略。
- API Key 只通过环境变量注入，不要写入代码、README、日志或 Git 历史。
- `CORS_ORIGINS=*` 适合本地快速启动；如果前后端分离或暴露在受控网络之外，应改为明确的来源列表。
- 默认单文件限制为 100 MB，并发模型调用默认限制为 2；高并发使用前应评估 LLM 限流和主机资源。
- 提交前应运行后端回归测试、Python 编译检查和 Docker 配置检查；涉及界面行为时还应完成人工功能验证。
- 项目不提供公网在线服务地址；需要使用时请自行在可信环境部署。

## 许可证

本项目采用 [MIT License](LICENSE)。
