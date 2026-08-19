# 技术栈改进计划

## 1. LLM JSON 提取健壮性改进 ✅ 已完成 (2026-07-19)

### 问题分析

当前 `extract_json()` 位于 `backend/app/services/llm_client.py:226`，存在以下脆弱点：

1. **中文 LLM 习惯在 JSON 前后输出推理文字**，正则剥离策略无法穷举所有变体（如以"好的，根据分析..."、"基于以上判断..."开头）
2. **`<think>` 标签处理不完整**：只处理了闭合和未闭合的 `<think>`，但 DeepSeek-R1 等模型还输出 `<reasoning>`、`<analysis>` 等标签
3. **逐策略尝试 JSON 提取**：先找 `{` 到 `}`，失败后从后往前找，再失败后修尾随逗号——每次失败都要重试解析，逻辑分支过多
4. **单引号 JSON 替换过于粗暴**：`text.replace("'", '"')` 会把字符串内容中的单引号也替换掉，破坏数据
5. **校验时只检查 `has_issue=true` 时的 reason**，`has_issue=false` 时 reason 可以为空或垃圾值，导致下游展示异常
6. **无结构化输出的兜底方案**：当 `function_call` 返回空而 `content` 也提取失败时，直接抛异常，没有容错策略

### 改进方案

#### 1.1 迁移到 tool_calls（废弃 function_call）

OpenAI Python SDK v1.0+ 已废弃 `functions` 参数，当前使用的 `function_call` 方式在部分兼容 API 上行为不稳定。

```python
# 旧方式（已废弃）
kwargs["functions"] = [function_schema]
kwargs["function_call"] = "auto"

# 新方式
kwargs["tools"] = [{"type": "function", "function": function_schema}]
kwargs["tool_choice"] = "auto"
```

解析侧同步修改：
```python
# 旧方式
if msg.function_call:
    result = json.loads(msg.function_call.arguments)

# 新方式
if msg.tool_calls:
    result = json.loads(msg.tool_calls[0].function.arguments)
```

#### 1.2 `extract_json` 健壮性重构

将多级兜底策略改为**确定性更强的单一提取管道**：

```
输入文本
  ├─ 1. 去除所有已知推理标签 (<think>, <reasoning>, <analysis>, <response> 等)
  ├─ 2. 去除 markdown 代码块 (```json ... ```)
  ├─ 3. 使用正则提取最外层完整 JSON 对象（括号匹配计数，而非盲目找 { 和 }）
  ├─ 4. 修复常见 JSON 格式问题：
  │     ├─ 尾随逗号
  │     ├─ 中文引号 → 英文引号
  │     ├─ 单引号 key/value（仅替换结构引号，保护字符串内单引号）
  │     └─ 未转义的控制字符
  └─ 5. json.loads 解析
```

关键改进点：

- **用括号计数器找最外层 `{}`**，而非简单的 `text.find('{')` + `text.rfind('}')`
- **单引号替换改为上下文感知**：只替换 key 周围的单引号和 value 的结构引号，保留字符串内容中的单引号（用正则 `(?<!\\)'` 配合上下文）
- **添加常见中文标点修复**：`"..."` → `"..."`，`'...'` → `'...'`

#### 1.3 引入结构化输出校验层

新增 `validate_and_repair()` 函数，在 `json.loads` 成功后对字段做二次校验和自动修复：

| 字段 | 校验规则 | 自动修复 |
|------|---------|---------|
| `has_issue` | 必须是 bool | `"是"/"存在"` → `true`，`"否"/"无"` → `false` |
| `risk_level` | 必须是 `高/中/低/人工复核` | 模糊匹配，"高风险" → "高"，"中等" → "中" |
| `reason` | 非空字符串 | 若为空，填入 `"模型未提供具体理由"` |
| `suggestion` | 若 `has_issue=true` 则非空 | 若为空，填入 `"建议人工复核"` |
| M3 特有字段 | `scene_type` 必须在枚举中 | 模糊匹配到最近枚举值，否则标记 `"unclear"` |

#### 1.4 增加 LLM 输出失败后的兜底策略

当前失败 → 直接抛异常 → 任务标记为 `api_error`。改为：

1. **第 1 次失败**：追加明确的格式纠正提示，重试
2. **第 2 次失败**：降低 temperature 到 0，关闭 tool_choice（纯文本模式），重试
3. **第 3 次失败**：使用最宽松的 `extract_json` 从 content 兜底提取
4. **全部失败**：返回一个带 `status: "parse_error"` 的结构化错误结果，而非裸异常

---

## 2. 异步架构重构

### 问题

`ThreadPoolExecutor` + 每线程内 `asyncio.run()` 创建独立事件循环，导致：
- 8 线程同时处理时，每线程各自启动事件循环，资源浪费
- 信号量跨线程工作但线程大部分时间在阻塞等待
- 无法真正利用 asyncio 的并发优势

### 方案

- 移除 `ThreadPoolExecutor`，改为 `asyncio.gather` + `asyncio.Semaphore` 控制并发
- 文件级并发 + 模型级并发统一在单个事件循环中管理
- 参考架构：`asyncio.Semaphore(LLM_MAX_CONCURRENT)` 控制 LLM 并发，`asyncio.Semaphore(FILE_MAX_CONCURRENT)` 控制文件解析并发

---

## 3. 数据持久化：JSON 文件 → SQLite

### 问题

- 文件 I/O 无事务保证，写入中途崩溃会导致数据损坏
- 历史记录列表需遍历所有文件并排序，文件多时性能差
- 并发读写无保护（虽然当前单进程，但未来扩展受限）

### 方案

- 引入 `aiosqlite`（异步）或标准库 `sqlite3`（同步）
- 两张表：`tasks`（进行中的任务）、`history`（已完成的历史记录）
- 保留 CSV 文件导出功能，SQLite 只存结构化数据
- 迁移成本低：SQLite 无需额外服务，`data/` 目录下多一个 `.db` 文件

---

## 4. Prompt 外部化管理

### 问题

- 所有 prompt 硬编码在 `backend/app/main.py`，约 300 行
- 改 prompt = 改代码 + 重新构建镜像 + 重新部署
- 无法做效果对比，无法追踪 prompt 变更历史

### 方案

- 将 prompt 模板抽到 `backend/prompts/` 目录下的 YAML 文件中
- 每个模型一个文件，包含 system_prompt、user_prompt_template、few-shot examples
- 启动时加载到内存，支持运行时热重载（监听文件变化或提供 reload API）
- 后续可扩展到数据库中管理，配合版本号

---

## 5. 前端可维护性

### 问题

- 2000+ 行单文件 HTML，HTML/CSS/JS 混杂
- 无组件抽象，加新功能需在单文件中定位
- 无构建步骤，无法使用 TypeScript、模块化等

### 方案

短期（低成本）：
- 用 Alpine.js 做响应式绑定，分离 JS 逻辑
- CSS 抽到独立文件

长期：
- Vue 3 + Vite，组件化拆分（上传区、进度区、结果表、历史侧边栏）
- 可渐进迁移，先抽最复杂的部分

---

## 6. 安全加固

- **速率限制**：`slowapi` 对 `/review/batch` 做 IP 级别限流
- **CORS 收紧**：生产环境仅允许前端域名
- **API Key 认证**：简单的 Header token 校验，防止公网滥用
- **文件上传校验**：已有大小限制，补充文件类型魔数校验（防伪造扩展名）

---

## 7. Prompt Caching

### 方案

- 将固定的规则说明和 few-shot examples 放在 system prompt 中
- 利用 OpenAI/Anthropic 的 automatic prompt caching
- 预估节省：当前 prompt 中 ~70% 内容是固定的（判断规则 + 示例），仅 ~30% 是变化的判决书文本

---

## 8. 可观测性

- `structlog` 输出 JSON 格式结构化日志
- 每次请求生成 `request_id` 贯穿全链路
- LLM 调用记录：延迟、token 消耗、重试次数、成功/失败
- 简单的 `/health` 端点扩展：检查 LLM API 可达性

---

## 优先级建议

| 优先级 | 改进项 | 投入 | 收益 |
|--------|--------|------|------|
| **P0** | JSON 提取健壮性 | 2-3天 | 直接影响审查成功率 |
| P1 | 异步架构重构 | 3-5天 | 性能翻倍，代码简化 |
| P1 | SQLite 替换 JSON | 1-2天 | 数据可靠性 |
| P2 | Prompt 外部化 | 1-2天 | 迭代效率 |
| P3 | 前端可维护性 | 3-5天 | 长期维护 |
| P3 | 安全加固 | 1天 | 合规 |
| P3 | Prompt Caching | 0.5天 | 成本 |
| P3 | 可观测性 | 1天 | 运维效率 |
