# 评测体系（Eval）

本目录提供一套轻量的迭代评测基础设施，用于验证 AI 智能体系统优化前后的效果。

## 目录结构

```
eval/
├── cases/              # 评测集（JSONL）
│   └── baseline.jsonl  # 基线样例集
├── results/            # 每轮运行的结果（JSONL）
├── scripts/
│   ├── run_eval.py     # 跑批脚本：调用后端对话接口，收集结果与指标
│   └── compare_eval.py # 对比分析：比较两个 run 的指标变化与回归
```

## 评测维度

| 维度 | 指标 | 说明 |
|---|---|---|
| 准确性 | accuracy / contains 命中 | 关键信息是否包含、错误信息是否泄露 |
| 工具调用 | tool_calls 匹配 | 是否调用了正确的工具（预留字段） |
| 拒答能力 | should_refuse | 该拒答时是否拒答 |
| 幻觉 | not_contains | 是否编造不存在的引用/事实 |
| 性能 | first_token_latency_ms / total_latency_ms | 首 token 与端到端延迟 |
| 稳定性 | stream_complete / status | SSE 是否完整、有无报错 |

## 样例选取标准

- **核心场景（~60%）**：知识库问答、多轮对话、工具调用、多智能体 Flow
- **边界场景（~25%）**：空输入、多语言、长文本、超长上下文
- **对抗/回归（~15%）**：拒答、幻觉诱导、越权尝试、已知 bad case

## 数据格式

评测集（cases/*.jsonl），每行一个用例：

```json
{
  "id": "case_001",
  "category": "knowledge_qa",
  "agent_type": "origin",
  "query": "公司的年假政策是什么？",
  "context": {"kb_id": 3},
  "expected": {
    "contains": ["年假"],
    "not_contains": ["不确定"],
    "tool_calls": [],
    "should_refuse": false
  },
  "reference_docs": ["doc_12_para3"],
  "tags": ["core", "accuracy"]
}
```

## 使用方法

### 1. 跑基线

```bash
python eval/scripts/run_eval.py \
  --cases eval/cases/baseline.jsonl \
  --run-id iter_00_baseline \
  --base-url http://localhost:8080 \
  --agent-id 1
```

### 2. 做优化

（修改代码、调提示词、调 RAG 参数等）

### 3. 跑优化后

```bash
python eval/scripts/run_eval.py \
  --cases eval/cases/baseline.jsonl \
  --run-id iter_01_opt \
  --base-url http://localhost:8080 \
  --agent-id 1
```

### 4. 对比分析

```bash
python eval/scripts/compare_eval.py \
  --baseline eval/results/iter_00_baseline.jsonl \
  --current eval/results/iter_01_opt.jsonl
```

## 迭代建议节奏

1. **第0轮**：跑基线，建立指标基线
2. **第1轮**：基础设施优化（懒加载/缓存）→ 验证延迟下降
3. **第2轮**：补单测 → 验证正确性
4. **第3轮**：异常处理/日志 → 验证稳定性
5. **第4轮**：提示词/RAG 参数调优 → 验证准确率/召回

## 注意事项

- 每个 run 用唯一 `run-id`，结果存 `results/<run-id>.jsonl`，可追溯。
- 回归护栏：优化后若任一 `tags` 含 `p0` 的用例从"通过"变"失败"，应回退该优化。
- 性能指标用中位数更稳健（当前脚本输出均值，可自行扩展）。
- 对话接口依赖登录态（若后端开了鉴权），跑批前需在脚本里补充 token 注入。
