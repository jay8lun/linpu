# 评测体系（Eval）

本目录提供一套轻量的迭代评测基础设施，用于验证 AI 智能体系统优化前后的效果。

## 目录结构

```
eval/
├── cases/                  # 评测集（JSONL）
│   ├── full_200.jsonl      # 完整集：200 条，6 个维度
│   ├── baseline.jsonl      # 冒烟集：8 条，快速验证链路
│   ├── knowledge_qa.jsonl  # 分维度：知识库问答 60
│   ├── general_qa.jsonl    # 分维度：通用问答 30
│   ├── tool_call.jsonl     # 分维度：工具调用 30
│   ├── multi_turn.jsonl    # 分维度：多轮记忆 20
│   ├── refusal.jsonl       # 分维度：拒答安全 30
│   └── hallucination.jsonl # 分维度：幻觉对抗 30
├── kb/                     # 知识库语料（评测专用）
│   └── linpu-platform-manual.md   # 60 小节的平台技术手册
├── results/                # 每轮运行的结果（JSONL）
└── scripts/
    ├── gen_cases.py        # 生成/重建评测集（改模板后重跑）
    ├── patch_kb_assertions.py   # 给知识库用例补有区分度的断言
    ├── ingest_kb_sections.py    # 按小节切分并写入 pgvector
    ├── run_eval.py         # 跑批：调用后端对话接口，收集结果与指标
    └── compare_eval.py     # 对比分析：指标变化 + 回归检测
```

## 样本规模与统计意义

| 样本量 | 95% 置信区间半宽（p=0.8） | 用途 |
|---|---|---|
| 8 | ±28% | 只能验证链路通不通 |
| 30 | ±14% | 看大趋势 |
| 50 | ±11% | 勉强可用 |
| 100 | ±7.8% | 可用 |
| 200 | ±5.5% | 结论稳健 |

**判据**：优化后指标提升幅度必须大于置信区间半宽，才能宣称有真实改进。200 条下，提升 <5.5% 视为噪声。

## 评测维度与配额

| 维度 | 条数 | 测什么 | 依赖 |
|---|---|---|---|
| knowledge_qa | 60 | RAG 召回与引用准确性 | 需知识库 |
| general_qa | 30 | 通识准确性 | 无 |
| tool_call | 30 | 工具选择是否正确 | 需挂载工具 |
| multi_turn | 20 | 多轮上下文记忆 | 无 |
| refusal | 30 | 违规请求是否拒答 | 无 |
| hallucination | 30 | 不存在的内容是否编造 | 部分需知识库 |

## 数据格式

每行一个用例（JSONL）。**单轮**用 `query`，**多轮**用 `turns`（同一 session 连续提问）：

```json
{
  "id": "mt_002",
  "category": "multi_turn",
  "turns": ["我记住一个数字：42。请回复「已记住」。", "我刚才让你记住的数字是多少？"],
  "expected": {
    "contains": ["42"],
    "not_contains": [],
    "tool_calls_allowed": [],
    "tool_calls_forbidden": [],
    "should_refuse": false
  },
  "tags": ["memory"]
}
```

**需知识库的用例**加 `requires`，环境不支持时自动跳过：

```json
{
  "id": "kb_001",
  "category": "knowledge_qa",
  "requires": ["knowledge_base"],
  "query": "根据知识库内容，这份文档的核心结论是什么？",
  "expected": { "contains": [], "not_contains": ["没有找到相关"], "should_refuse": false }
}
```

### 字段说明

| 字段 | 必填 | 说明 |
|---|---|---|
| `id` | 是 | 唯一标识，跨轮次比对用 |
| `category` | 是 | 维度分类 |
| `query` / `turns` | 是（二选一） | 单轮输入 / 多轮输入 |
| `requires` | 否 | 运行依赖，如 `["knowledge_base"]` |
| `expected.contains` | 否 | 必须出现的关键词（全命中才通过） |
| `expected.not_contains` | 否 | 不应出现的关键词（出现即失败） |
| `expected.tool_calls_allowed` | 否 | 必须调用其中之一（非空时校验） |
| `expected.tool_calls_forbidden` | 否 | 一律不得调用 |
| `expected.should_refuse` | 否 | 是否应拒答（空输出视为正确拒答） |

## 使用方法

### 0. 先干跑，确认将执行多少条

```bash
python eval/scripts/run_eval.py --cases eval/cases/full_200.jsonl \
  --run-id dry --agent-id 1 --dry-run
# 无任何依赖：执行 132 / 跳过 68
# 加 --has-kb：执行 192 / 跳过 8（那 8 条需要联网搜索）
# 再加 --has-web-search：执行 200 / 跳过 0
```

### 0.1 搭建知识库（可选，跑 knowledge_qa 维度需要）

`knowledge_qa` 的 60 条用例断言的是**手册里才有的特征值**（如错误码 `LP-4001`、
端口 `18142`），因此必须先把手册灌进知识库，否则会正确判为失败。

```bash
# 1) 登录拿 token（生产开启了验证码，需先临时关闭 sys.account.captchaEnabled）
# 2) 新建知识库
curl -X POST http://localhost:8080/ai/knowledgeBase \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"name":"linpu 平台技术手册"}'

# 3) 上传文档
curl -X POST http://localhost:8080/common/upload \
  -H "Authorization: Bearer $TOKEN" -F "file=@eval/kb/linpu-platform-manual.md"

# 4) 确认默认向量模型已就绪
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8080/ai/knowledgeBase/check-embedding-dimension

# 5) 按小节切分写入 pgvector（比按字符切分召回更准）
python eval/scripts/ingest_kb_sections.py
docker cp eval/results/_kb_sections.sql pgvector:/tmp/kb.sql
docker exec -e PGPASSWORD=root pgvector \
  psql -U root -d embedding -f /tmp/kb.sql

# 6) 把知识库绑定到智能体：kb_ids='1'，且 prompt_template 必须包含 {data} 和 {question}
```

> 注意：`prompt_template` 里没有 `{data}` 占位符时，后端**不会**做检索。

### 1. 跑基线

```bash
python eval/scripts/run_eval.py --cases eval/cases/full_200.jsonl \
  --run-id iter_00_baseline --base-url http://localhost:8080 \
  --agent-id 1 --token <你的JWT> --has-kb
```

### 2. 做优化

（改代码 / 调提示词 / 调 RAG 参数）

### 3. 跑优化后

```bash
python eval/scripts/run_eval.py --cases eval/cases/full_200.jsonl \
  --run-id iter_01_opt --base-url http://localhost:8080 \
  --agent-id 1 --token <你的JWT> --has-kb
```

### 4. 对比分析

```bash
python eval/scripts/compare_eval.py \
  --baseline eval/results/iter_00_baseline.jsonl \
  --current eval/results/iter_01_opt.jsonl
```

### 重建评测集

修改 `gen_cases.py` 里的模板后重跑，会同时输出分维度文件和合并的 `full_200.jsonl`：

```bash
python eval/scripts/gen_cases.py
```

## 迭代节奏建议

1. **第0轮**：跑基线，建立指标基线
2. **第1轮**：基础设施优化（懒加载/缓存）→ 验证延迟下降
3. **第2轮**：补单测 → 验证正确性
4. **第3轮**：异常处理/日志 → 验证稳定性
5. **第4轮**：提示词/RAG 参数调优 → 验证准确率/召回

## 已知限制（实测发现）

**内置本地向量模型区分度不足**。默认向量模型 `text2vec-base-chinese`（ONNX，768 维）
对同领域长中文文本的基线相似度很高：同一篇手册中 60 个不同小节的向量两两余弦相似度
普遍落在 0.75–0.92，而语义正确匹配的章节与其他章节的分数差通常只有 0.01–0.03。
后果是排序接近随机，`knowledge_qa` 维度准确率显著偏低。

已排除代码问题：把库里存的向量取出来，用 Python 按同样方式（ONNX + mean pooling +
L2 归一化）重算，余弦相似度为 **1.0**，即应用侧向量化实现正确。

改进方向（按性价比排序）：
1. 换更强向量模型（如 bge-large-zh-v1.5，需维度同为 768 或同步调整 `pgvector.dimension`）；
2. 引入关键词检索（BM25）与向量检索混合排序；
3. 在分段中保留标题并做「标题 + 正文」双字段打分。

## 注意事项

- 每个 run 用唯一 `--run-id`，结果存 `results/<run-id>.jsonl`，可追溯。
- **回归护栏**：优化后若任一 `tags` 含 `p0` 的用例从"通过"变"失败"，应回退该优化。
- 断言设计原则：`not_contains` 要选**幻觉特征词**（如"条款如下""第X条"），不要选问题里本身出现的词，否则会误伤。
- 后端开启鉴权时必须传 `--token`；否则全部 401。
- 性能指标当前输出均值，长尾场景建议改用中位数（可自行扩展 `run_eval.py`）。
- 依赖 `requests`（可选）；未安装时自动回退 urllib。
