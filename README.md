# 民事判决书智能监督模型

AI 驱动的民事判决书审查系统，自动检测判决书中的四类常见问题。

## 功能介绍

系统包含四个检测模型：

| 模型 | 名称 | 检测问题 |
|------|------|----------|
| M1 | 公告费 | 法院公告送达但未判决公告费 |
| M3 | 合同解除时间 | 合同解除时间认定错误（民法典第563/565条） |
| M5 | 诉讼费 | 案件受理费、申请费直接支付给胜诉方（应向法院交纳） |
| M10 | 加倍利息 | 金钱给付义务未载明加倍支付迟延履行利息 |

### 特色功能

- **实时进度**：SSE 实时推送分析进度
- **历史记录**：左侧边栏永久保存审查记录，支持查看详情和下载CSV
- **响应式设计**：完美支持桌面端和移动端

## 技术架构

```
前端 (HTML SPA)  ←→  Nginx  ←→  后端 (FastAPI)  ←→  MiniMaxAPI
```

- **后端**：Python 3.11 + FastAPI，支持批量处理、SSE 实时推送
- **前端**：纯 HTML 单页应用，无需构建，响应式设计
- **容器**：Docker + Docker Compose，一键部署
- **数据**：JSON 文件持久化，历史记录永久保存

## 环境要求

- Docker Desktop（容器运行需要）
- MiniMax API Key（或兼容 OpenAI 格式的其他 API）

## 快速开始

### 方式一：Docker（推荐）

```bash
# 1. 克隆项目后，复制环境变量模板
cp .env.example .env

# 2. 编辑 .env，填入你的 API Key
# OPENAI_API_KEY=sk-xxxxxxxx
# OPENAI_BASE_URL=xxxxxxxx
# MODEL_NAME=xxxxxxxx

# 3. 启动所有服务
docker-compose up -d --build

# 4. 访问前端
# http://localhost:8080
```

### 方式二：本地 Python 运行

**后端：**
```bash
cd backend
pip install -r requirements.txt
python run.py
# 服务运行在 http://localhost:8000
```

**前端：**
```bash
# 直接用浏览器打开 frontend/index.html
# 或使用任意静态服务器
cd frontend
python -m http.server 8080
# 访问 http://localhost:8080
```

## 环境变量

| 变量名 | 说明 | 示例 |
|--------|------|------|
| `OPENAI_API_KEY` | API 密钥 | `sk-xxxxxxxx` |
| `OPENAI_BASE_URL` | API 地址（兼容 OpenAI 格式） | `https://xxxxxxxx` |
| `MODEL_NAME` | 模型名称 | `xxxxxxxx` |
| `DEBUG_LOG` | 是否开启调试日志 | `false` |
| `CORS_ORIGINS` | 允许的来源 | `*` |

## API 接口

| 方法 | 路径 | 说明 |
|------|------|------|
| `POST` | `/review/batch` | 批量上传判决书文件（支持 .doc/.docx/.pdf/.txt） |
| `GET` | `/review/stream/{task_id}` | SSE 实时推送分析进度 |
| `GET` | `/review/batch/{task_id}` | 查询任务状态 |
| `GET` | `/review/download/{filename}` | 下载结果 CSV 文件 |
| `GET` | `/review/history` | 获取历史记录列表 |
| `GET` | `/review/history/{task_id}` | 获取历史记录详情 |
| `DELETE` | `/review/history/{task_id}` | 删除单条历史记录 |
| `DELETE` | `/review/history` | 清除全部历史记录 |

## 目录结构

```
legalsupervesion/
├── backend/
│   ├── app/
│   │   ├── services/          # 核心服务（解析、LLM调用、regex过滤）
│   │   ├── models/             # 数据模型
│   │   ├── main.py             # FastAPI 应用
│   │   └── config.py           # 配置
│   ├── Dockerfile
│   ├── .dockerignore            # Docker 构建排除文件
│   ├── requirements.txt
│   └── run.py                  # 入口文件
├── frontend/
│   ├── index.html              # 单页应用（响应式设计）
│   └── nginx.conf              # Nginx 配置
├── data/                        # 数据目录
│   ├── history/                # 永久历史记录
│   ├── results/                # CSV 结果文件
│   ├── tasks/                  # 临时任务文件
│   └── uploads/                # 用户上传文件
├── docker-compose.yml
├── .env.example
└── README.md
```

## 注意事项

1. **文件格式**：支持 `.doc`、`.docx`、`.pdf`、`.txt`
2. **PDF 解析**：依赖 PyMuPDF 库提取文本
2. **并发控制**：LLM 并发数默认限制为 2，避免 API 限流
3. **数据持久化**：历史记录保存在 `data/history/`，删除容器不丢失
4. **移动端**：支持响应式设计，可在手机端使用，左上角📋按钮打开历史记录
