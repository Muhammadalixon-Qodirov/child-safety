"""Runs the synthetic test set through the classifier and writes eval/results.md.

    python -m eval.run_eval            # uses Groq if GROQ_API_KEY is set, otherwise keywords
"""
import json
from collections import Counter
from pathlib import Path

from backend import ai_engine

HERE = Path(__file__).parent


def main():
    cases = [json.loads(l) for l in (HERE / "test_cases.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    rows, tp, fp, fn, tn, exact = [], 0, 0, 0, 0, 0
    per_cat = Counter()
    for c in cases:
        r = ai_engine.classify_text(c["text"], {"age_group": "10-13"})
        pred_unsafe = r["category"] != "SAFE" and r["risk"] >= 30
        true_unsafe = c["label"] != "SAFE"
        tp += pred_unsafe and true_unsafe
        fp += pred_unsafe and not true_unsafe
        fn += true_unsafe and not pred_unsafe
        tn += not pred_unsafe and not true_unsafe
        ok = r["category"] == c["label"] or (c["label"] == "SAFE" and not pred_unsafe)
        exact += ok
        per_cat[(c["label"], ok)] += 1
        rows.append((c["label"], r["category"], r["risk"], "✅" if ok else "❌", c["text"][:60]))
    precision = tp / max(tp + fp, 1)
    recall = tp / max(tp + fn, 1)
    engine = rows and ai_engine.classify_text(cases[0]["text"])["engine"]
    lines = [
        "# Guardian classifier evaluation", "",
        f"Engine: `{engine}` · {len(cases)} synthetic cases (English, Uzbek, Russian)", "",
        "| Metric | Value |", "|---|---|",
        f"| Unsafe-vs-safe precision | {precision:.0%} |",
        f"| Unsafe-vs-safe recall | {recall:.0%} |",
        f"| Exact category accuracy | {exact / len(cases):.0%} |",
        f"| False alarms on safe content | {fp} / {fp + tn} |", "",
        "| Expected | Predicted | Risk | OK | Text |", "|---|---|---|---|---|",
        *[f"| {a} | {b} | {c} | {d} | {e} |" for a, b, c, d, e in rows],
    ]
    (HERE / "results.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:10]))


if __name__ == "__main__":
    main()
