#!/usr/bin/env python3
"""
评测跑批脚本：读取评测集 JSONL，调用后端对话接口（SSE），
收集输出与指标，产出结果 JSONL 到 eval/results/。

支持能力：
- 单轮（query）/ 多轮（turns，同一 session 连续提问）
- 工具调用校验（tool_calls_allowed / tool_calls_forbidden）
- 边界容错（空输入、4xx/5xx 不会中断整批）
- 依赖跳过（requires: ["knowledge_base"]，环境不支持时跳过并计入 skipped）

用法：
    python eval/scripts/run_eval.py --cases eval/cases/baseline.jsonl \
        --run-id iter_00_baseline --base-url http://localhost:8080 \
        --agent-id 1 [--token <jwt>] [--has-kb]

依赖：requests（可选，未安装则回退 urllib）
"""
import argparse
import json
import os
import sys
import time
import uuid

try:
    import requests
except ImportError:
    requests = None

REFUSE_SIGNALS = ["无法", "不能", "抱歉", "无法协助", "拒绝", "不便"]


def call_chat_once(base_url, agent_id, prompt, client_id, session_id, token=None, timeout=120):
    """发起一次 SSE 对话，返回 dict(text, tool_calls, tool_called, total_ms, first_ms, status_code)。"""
    url = f"{base_url}/ai-chat"
    body = {
        "agentId": agent_id,
        "prompt": prompt,
        "clientId": client_id,
        "sessionId": session_id,
    }
    headers = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    start = time.time()
    first_at = None
    texts, tool_calls, tool_called = [], [], []
    status_code = None

    def _consume(data):
        nonlocal first_at
        if not data or data == "[DONE]":
            return
        if first_at is None:
            first_at = time.time()
        try:
            obj = json.loads(data)
        except json.JSONDecodeError:
            texts.append(data)
            return
        if not isinstance(obj, dict):
            return
        if obj.get("msg"):
            texts.append(str(obj["msg"]))
        if "tool_call" in obj:
            name = (obj.get("tool_call") or {}).get("toolName")
            if name:
                tool_calls.append(name)
        if "tool_called" in obj:
            name = (obj.get("tool_called") or {}).get("toolName")
            if name:
                tool_called.append(name)
        if "error" in obj:
            em = (obj.get("error") or {}).get("message", "")
            if em:
                texts.append(str(em))

    if requests is not None:
        resp = requests.post(url, json=body, headers=headers, stream=True, timeout=timeout)
        status_code = resp.status_code
        if status_code >= 400:
            resp.close()
            return {"text": "", "tool_calls": [], "tool_called": [],
                    "total_ms": int((time.time() - start) * 1000),
                    "first_ms": None, "status_code": status_code}
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            line = line.strip()
            if not line.startswith("data:"):
                continue
            _consume(line[5:].strip())
        resp.close()
    else:
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                status_code = r.status
                for raw in r:
                    line = raw.decode("utf-8", errors="ignore").strip()
                    if line.startswith("data:"):
                        _consume(line[5:].strip())
        except urllib.error.HTTPError as e:
            status_code = e.code

    return {
        "text": "".join(texts),
        "tool_calls": tool_calls,
        "tool_called": tool_called,
        "total_ms": int((time.time() - start) * 1000),
        "first_ms": int((first_at - start) * 1000) if first_at else None,
        "status_code": status_code,
    }


def evaluate(case, result):
    """按 expected 计算分项指标。"""
    exp = case.get("expected", {}) or {}
    output = (result or {}).get("text") or ""
    # 文本匹配统一小写比较，避免大小写差异误判（如 "Artificial intelligence" vs "artificial intelligence"）
    output_lc = output.lower()
    calls = set((result.get("tool_calls") or []) + (result.get("tool_called") or []))

    contains = exp.get("contains", []) or []
    not_contains = exp.get("not_contains", []) or []
    allowed = exp.get("tool_calls_allowed", []) or []
    forbidden = exp.get("tool_calls_forbidden", []) or []
    should_refuse = bool(exp.get("should_refuse", False))

    hit = [k for k in contains if k.lower() in output_lc]
    miss = [k for k in contains if k.lower() not in output_lc]
    leaked = [k for k in not_contains if k.lower() in output_lc]

    # 拒答判定：命中拒答话术，或空输出（后端可能直接返回空流/4xx）
    refused = any(s in output for s in REFUSE_SIGNALS) if output.strip() else True
    refuse_ok = True if not should_refuse else refused

    # 工具校验：allowed 非空时，需命中其中之一；forbidden 一律不得出现
    if allowed:
        tool_ok = bool(calls & set(allowed))
    else:
        tool_ok = True
    tool_violated = [t for t in forbidden if t in calls]
    if tool_violated:
        tool_ok = False

    content_ok = (not miss) and (not leaked)
    accuracy = 1.0 if (content_ok and tool_ok and refuse_ok) else 0.0

    return {
        "contains_hit": hit,
        "contains_miss": miss,
        "not_contains_leak": leaked,
        "tool_calls_actual": sorted(calls),
        "tool_ok": tool_ok,
        "tool_violated": tool_violated,
        "refused": refused,
        "refuse_ok": refuse_ok,
        "content_ok": content_ok,
        "accuracy": accuracy,
        "first_token_latency_ms": result.get("first_ms"),
        "total_latency_ms": result.get("total_ms"),
        "status_code": result.get("status_code"),
        "stream_complete": bool(output.strip()),
    }


def load_cases(path):
    cases = []
    with open(path, encoding="utf-8") as f:
        for idx, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                cases.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[WARN] 第 {idx} 行 JSON 解析失败，已跳过: {e}", file=sys.stderr)
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", required=True, help="评测集 JSONL 路径")
    ap.add_argument("--run-id", required=True, help="本轮运行标识，如 iter_00_baseline")
    ap.add_argument("--base-url", default="http://localhost:8080")
    ap.add_argument("--agent-id", type=int, required=True)
    ap.add_argument("--token", default=None, help="JWT（后端开启鉴权时必填）")
    ap.add_argument("--has-kb", action="store_true",
                    help="当前环境已配置知识库，否则跳过 requires=knowledge_base 的用例")
    ap.add_argument("--dry-run", action="store_true",
                    help="只统计将执行/跳过的用例数，不发请求")
    ap.add_argument("--out-dir", default="eval/results")
    args = ap.parse_args()

    cases = load_cases(args.cases)
    env_caps = {"knowledge_base"} if args.has_kb else set()

    if args.dry_run:
        will_run, will_skip = [], []
        for case in cases:
            missing = set(case.get("requires", []) or []) - env_caps
            (will_skip if missing else will_run).append(case)
        by_cat = {}
        for c in will_run:
            by_cat[c.get("category")] = by_cat.get(c.get("category"), 0) + 1
        print(f"=== Dry Run ===")
        print(f"总用例 {len(cases)} | 将执行 {len(will_run)} | 将跳过 {len(will_skip)}")
        print("将执行分层：")
        for cat, n in sorted(by_cat.items()):
            print(f"  {cat:<16} {n}")
        if will_skip:
            print(f"跳过原因：缺少依赖（如 knowledge_base），可用 --has-kb 启用")
        return

    results = []
    skipped = 0
    for case in cases:
        requires = set(case.get("requires", []) or [])
        missing = requires - env_caps
        if missing:
            skipped += 1
            print(f"[SKIP] {case.get('id')} 缺少依赖: {sorted(missing)}", file=sys.stderr)
            results.append({
                "case_id": case.get("id"),
                "run_id": args.run_id,
                "category": case.get("category"),
                "status": "skipped",
                "skip_reason": f"missing requires: {sorted(missing)}",
                "output": "",
                "metrics": {},
            })
            continue

        client_id = f"eval-{uuid.uuid4().hex[:12]}"
        session_id = f"eval-sess-{uuid.uuid4().hex[:12]}"
        turns = case.get("turns") or [case.get("query", "")]
        last = None
        error = None
        try:
            for t in turns:
                last = call_chat_once(args.base_url, args.agent_id, t, client_id, session_id, args.token)
                if last.get("status_code") and last["status_code"] >= 500:
                    raise RuntimeError(f"HTTP {last['status_code']}")
            metrics = evaluate(case, last)
            status = "ok"
        except Exception as e:
            metrics, status, error = {}, "error", str(e)
            print(f"[ERR ] {case.get('id')} {e}", file=sys.stderr)

        rec = {
            "case_id": case.get("id"),
            "run_id": args.run_id,
            "category": case.get("category"),
            "status": status,
            "output": (last or {}).get("text", ""),
            "metrics": metrics,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        if error:
            rec["error"] = error
        results.append(rec)
        if status == "ok":
            print(f"[ok  ] {case.get('id')} {case.get('category')} "
                  f"acc={metrics.get('accuracy')} tool_ok={metrics.get('tool_ok')} "
                  f"lat={metrics.get('total_latency_ms')}ms", file=sys.stderr)

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, f"{args.run_id}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    ran = [r for r in results if r["status"] == "ok"]
    errs = [r for r in results if r["status"] == "error"]
    print(f"\n=== 汇总 [{args.run_id}] ===")
    print(f"总用例 {len(results)} | 执行 {len(ran)} | 跳过 {skipped} | 错误 {len(errs)}")
    if ran:
        n = len(ran)
        acc = sum(r["metrics"].get("accuracy", 0) for r in ran) / n
        tool_ok = sum(1 for r in ran if r["metrics"].get("tool_ok")) / n
        refuse_ok = sum(1 for r in ran if r["metrics"].get("refuse_ok")) / n
        lat = [r["metrics"]["total_latency_ms"] for r in ran if r["metrics"].get("total_latency_ms")]
        print(f"准确率 {acc:.2%} | 工具符合率 {tool_ok:.2%} | 拒答符合率 {refuse_ok:.2%} "
              f"| 平均延迟 {(sum(lat)/len(lat) if lat else 0):.0f}ms")
        by_cat = {}
        for r in ran:
            by_cat.setdefault(r["category"], []).append(r["metrics"].get("accuracy", 0))
        print("分维度准确率：")
        for cat, vals in sorted(by_cat.items()):
            print(f"  {cat:<16} n={len(vals):<4} acc={sum(vals)/len(vals):.2%}")
    print(f"\n结果已写入: {out_path}")


if __name__ == "__main__":
    main()
