#!/usr/bin/env python3
"""
评测跑批脚本：读取评测集 JSONL，调用后端 /ai-chat 接口（SSE），
收集输出与指标，产出结果 JSONL 到 eval/results/。

用法：
    python eval/scripts/run_eval.py --cases eval/cases/baseline.jsonl \
        --run-id iter_00_baseline --base-url http://localhost:8080 --agent-id 1

依赖：requests（可选，若不装则用 urllib）
"""
import argparse
import json
import sys
import time
import uuid

try:
    import requests
except ImportError:
    requests = None


def call_chat(base_url, agent_id, prompt, client_id, session_id, timeout=120):
    """调用后端 SSE 对话接口，返回 (完整文本, 事件列表, 耗时ms, 首token耗时ms)。"""
    url = f"{base_url}/ai-chat"
    body = {
        "agentId": agent_id,
        "prompt": prompt,
        "clientId": client_id,
        "sessionId": session_id,
    }
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}

    start = time.time()
    first_token_at = None
    full_text = []
    events = []

    if requests is not None:
        with requests.post(url, json=body, headers=headers, stream=True, timeout=timeout) as resp:
            for line in resp.iter_lines(decode_unicode=True):
                if line is None:
                    continue
                line = line.strip()
                if not line:
                    continue
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if first_token_at is None and data and data != "[DONE]":
                        first_token_at = time.time()
                    events.append(data)
                    # 尝试解析为 JSON 提取文本
                    try:
                        obj = json.loads(data)
                        txt = obj.get("content") or obj.get("text") or obj.get("msg") or ""
                        if txt:
                            full_text.append(txt)
                    except json.JSONDecodeError:
                        full_text.append(data)
    else:
        import urllib.request
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode().strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    if first_token_at is None and data and data != "[DONE]":
                        first_token_at = time.time()
                    events.append(data)
                    full_text.append(data)

    total_ms = int((time.time() - start) * 1000)
    first_ms = int((first_token_at - start) * 1000) if first_token_at else None
    return "".join(full_text), events, total_ms, first_ms


def evaluate(case, output):
    """根据 case 的 expected 计算指标。"""
    exp = case.get("expected", {})
    contains = exp.get("contains", [])
    not_contains = exp.get("not_contains", [])
    should_refuse = exp.get("should_refuse", False)

    hit = [kw for kw in contains if kw in output]
    miss = [kw for kw in contains if kw not in output]
    leaked = [kw for kw in not_contains if kw in output]

    refused = False
    refuse_signals = ["无法", "不能", "抱歉", "无法协助", "拒绝"]
    if should_refuse and output.strip():
        refused = any(s in output for s in refuse_signals)

    accuracy = 1.0 if not miss and not leaked else 0.0
    return {
        "contains_hit": hit,
        "contains_miss": miss,
        "not_contains_leak": leaked,
        "refused": refused,
        "accuracy": accuracy,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="评测集 JSONL 路径")
    ap.add_argument("--run-id", required=True, help="本轮运行标识，如 iter_00_baseline")
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--agent-id", type=int, required=True)
    ap.add_argument("--out-dir", default="eval/results")
    args = ap.parse_args()

    cases = []
    with open(args.cases, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    results = []
    for case in cases:
        client_id = f"eval-{uuid.uuid4().hex[:12]}"
        session_id = f"eval-sess-{uuid.uuid4().hex[:12]}"
        try:
            output, events, total_ms, first_ms = call_chat(
                args.base_url, args.agent_id, case["query"], client_id, session_id
            )
            metrics = evaluate(case, output)
            metrics["first_token_latency_ms"] = first_ms
            metrics["total_latency_ms"] = total_ms
            metrics["stream_events"] = len(events)
            metrics["stream_complete"] = bool(output.strip())
            status = "ok"
        except Exception as e:
            output, metrics, status = "", {}, "error"
            metrics["error"] = str(e)

        result = {
            "case_id": case["id"],
            "run_id": args.run_id,
            "category": case.get("category"),
            "status": status,
            "output": output,
            "metrics": metrics,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        results.append(result)
        print(f"[{status}] {case['id']} {case.get('category')} "
              f"acc={metrics.get('accuracy')} lat={metrics.get('total_latency_ms')}ms", file=sys.stderr)

    import os
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{args.run_id}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # 汇总
    total = len(results)
    ok = sum(1 for r in results if r["status"] == "ok")
    acc = [r["metrics"].get("accuracy", 0) for r in results if r["status"] == "ok"]
    avg_acc = sum(acc) / len(acc) if acc else 0
    lat = [r["metrics"].get("total_latency_ms") for r in results if r["status"] == "ok" and r["metrics"].get("total_latency_ms")]
    avg_lat = sum(lat) / len(lat) if lat else 0
    print(f"\n=== 汇总 [{args.run_id}] ===")
    print(f"总用例: {total} | 成功: {ok} | 平均准确率: {avg_acc:.2%} | 平均延迟: {avg_lat:.0f}ms")
    print(f"结果已写入: {out_path}")


if __name__ == "__main__":
    main()
