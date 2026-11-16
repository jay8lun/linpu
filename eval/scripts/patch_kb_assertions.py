"""为知识库用例补齐有区分度的断言。

原断言只有 not_contains（"知识库中没有"），无法区分「真检索到」与「模型自己编」。
这里为每条用例指定一个只在该章节出现过的特征字符串，写成 contains，
使通过与否真正反映检索命中质量。

特征值选取原则：
1. 只在目标章节出现的专有名词、数字、标识符；
2. 不在其他章节重复出现（避免歧义）；
3. 长度短、模型复述时容易原样保留（数字、编号、英文标识符优先）。
"""
import json
from pathlib import Path

CASES = Path("eval/cases/full_200.jsonl")

# case_id -> 该章节独有的特征字符串
KEY_MAP = {
    "kb_001": "一个 Java 单体",
    "kb_002": "六步",
    "kb_003": "四层",
    "kb_004": "懒加载",
    "kb_005": "Docker Compose",
    "kb_006": "掩码",
    "kb_007": "maxSegmentSize",
    "kb_008": "P95",
    "kb_009": "max_result",
    "kb_010": "LangChain4j",
    "kb_011": "text/event-stream",
    "kb_012": "ai.embedding.batchSize",
    "kb_013": "50 MB",
    "kb_014": "Flyway",
    "kb_015": "LP-4001",
    "kb_016": "Open AI",
    "kb_017": "13.x",
    "kb_018": "三类",
    "kb_019": "熔断",
    "kb_020": "pgvector",
    "kb_021": "traceId",
    "kb_022": "sessionId",
    "kb_023": "分段",
    "kb_024": "kb_ids",
    "kb_025": "1000",
    "kb_026": "八项",
    "kb_027": "03:00",
    "kb_028": "OpenAI 兼容",
    "kb_029": "LP-4006",
    "kb_030": "五步",
    "kb_031": "RBAC",
    "kb_032": "min_score",
    "kb_033": "行覆盖率",
    "kb_034": "8 核 16 GB",
    "kb_035": "0.7",
    "kb_036": "90 天",
    "kb_037": "主从复制",
    "kb_038": "traceId",
    "kb_039": "5%",
    "kb_040": "Bearer",
    "kb_041": "CRLF",
    "kb_042": "8192",
    "kb_043": "18142",
    "kb_044": "token",
    "kb_045": "15%",
    "kb_046": "两个大版本",
    "kb_047": "200 个并发",
    "kb_048": "五项",
    "kb_049": "页眉页脚",
    "kb_050": "30 秒",
    "kb_051": "maxSegmentSize",
    "kb_052": "/health",
    "kb_053": "15 分钟",
    "kb_054": "指数退避",
    "kb_055": "requestId",
    "kb_056": "120",
    "kb_057": "模型训练",
    "kb_058": "24 小时",
    "kb_059": "sess-001",
    "kb_060": "六个",
}


def main():
    lines = CASES.read_text(encoding="utf-8").splitlines()
    out, patched = [], 0
    for line in lines:
        if not line.strip():
            continue
        case = json.loads(line)
        cid = case.get("id")
        if cid in KEY_MAP:
            exp = case.setdefault("expected", {})
            exp["contains"] = [KEY_MAP[cid]]
            exp.setdefault("not_contains", [])
            if "没有找到相关" not in exp["not_contains"]:
                exp["not_contains"].append("没有找到相关")
            patched += 1
        out.append(json.dumps(case, ensure_ascii=False))
    CASES.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"已更新 {patched} 条知识库用例断言，总行数 {len(out)}")


if __name__ == "__main__":
    main()
