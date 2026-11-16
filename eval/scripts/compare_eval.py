#!/usr/bin/env python3
"""
评测结果对比分析：比较两个 run 的结果，输出指标变化与回归检测。

用法：
    python eval/scripts/compare_eval.py --baseline eval/results/iter_00_baseline.jsonl \
        --current eval/results/iter_01_opt.jsonl
"""
import argparse
import json


def load(path):
    data = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                r = json.loads(line)
                data[r["case_id"]] = r
    return data


def avg(lst):
    return sum(lst) / len(lst) if lst else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", required=True, help="优化前结果 JSONL")
    ap.add_argument("--current", required=True, help="优化后结果 JSONL")
    args = ap.parse_args()

    base = load(args.baseline)
    cur = load(args.current)

    common = set(base) & set(cur)
    print(f"=== 对比分析：{len(common)} 个共同用例 ===\n")

    # 汇总指标
    b_acc = [base[c]["metrics"].get("accuracy", 0) for c in common if base[c]["status"] == "ok"]
    c_acc = [cur[c]["metrics"].get("accuracy", 0) for c in common if cur[c]["status"] == "ok"]
    b_lat = [base[c]["metrics"].get("total_latency_ms") for c in common if base[c]["status"] == "ok" and base[c]["metrics"].get("total_latency_ms")]
    c_lat = [cur[c]["metrics"].get("total_latency_ms") for c in common if cur[c]["status"] == "ok" and cur[c]["metrics"].get("total_latency_ms")]

    print(f"{'指标':<20}{'优化前':>12}{'优化后':>12}{'变化':>12}")
    print("-" * 56)
    print(f"{'平均准确率':<20}{avg(b_acc):>11.2%}{avg(c_acc):>11.2%}{(avg(c_acc)-avg(b_acc)):>+11.2%}")
    print(f"{'平均延迟(ms)':<20}{avg(b_lat):>11.0f}{avg(c_lat):>11.0f}{(avg(c_lat)-avg(b_lat)):>+11.0f}")
    print(f"{'成功用例数':<20}{sum(1 for c in common if base[c]['status']=='ok'):>12}{sum(1 for c in common if cur[c]['status']=='ok'):>12}")

    # 回归检测
    print("\n=== 回归检测（优化前通过 → 优化后失败）===")
    regressions = []
    for c in sorted(common):
        b_ok = base[c]["status"] == "ok" and base[c]["metrics"].get("accuracy", 0) == 1.0
        c_ok = cur[c]["status"] == "ok" and cur[c]["metrics"].get("accuracy", 0) == 1.0
        if b_ok and not c_ok:
            regressions.append(c)
    if regressions:
        for c in regressions:
            print(f"  [回归] {c}: 优化前通过 → 优化后失败")
    else:
        print("  无回归")

    # 改进用例
    print("\n=== 改进用例（优化后通过 → 之前失败）===")
    improved = []
    for c in sorted(common):
        b_ok = base[c]["status"] == "ok" and base[c]["metrics"].get("accuracy", 0) == 1.0
        c_ok = cur[c]["status"] == "ok" and cur[c]["metrics"].get("accuracy", 0) == 1.0
        if c_ok and not b_ok:
            improved.append(c)
    if improved:
        for c in improved:
            print(f"  [改进] {c}")
    else:
        print("  无改进")


if __name__ == "__main__":
    main()
