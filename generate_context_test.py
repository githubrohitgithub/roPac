#!/usr/bin/env python3
"""
Generate context_test_100k.txt and benchmark long-context retrieval on a local Ollama model.

Usage:
  pip install faker openai
  python generate_context_test.py              # generate + run tests
  python generate_context_test.py --generate-only
  python generate_context_test.py --test-only
  python generate_context_test.py --model qwen2.5-coder:latest
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROPAC_ROOT = Path(__file__).resolve().parent
DEFAULT_OUTPUT = ROPAC_ROOT / "context_test_100k.txt"
DEFAULT_CONFIG = ROPAC_ROOT / "config.json"

SPECIAL_MEMORIES: list[tuple[str, str]] = [
    ("The blue tiger sleeps under the silver bridge.", "beginning"),
    ("Employee ID 84721 belongs to Jonathan Miles.", "middle"),
    ("The secret launch code is ORBIT-9921-X.", "deep_middle"),
    ("Rohit prefers analog watches over smartwatches.", "near_end"),
    ("The final verification number is 558391.", "end"),
]

NEGATIVE_PHRASES = (
    "not in",
    "not found",
    "no such",
    "does not contain",
    "doesn't contain",
    "do not contain",
    "don't contain",
    "no information",
    "not mentioned",
    "not present",
    "cannot find",
    "can't find",
    "no mars",
    "not in the document",
    "not in the file",
)


@dataclass
class TestCase:
    question: str
    expected_keywords: list[str]
    negative: bool = False
    label: str = ""


TEST_CASES: list[TestCase] = [
    TestCase(
        "What animal sleeps under the silver bridge?",
        ["blue tiger", "tiger"],
        label="fact_beginning",
    ),
    TestCase(
        "Which employee ID belongs to Jonathan Miles?",
        ["84721"],
        label="fact_middle",
    ),
    TestCase(
        "What is the secret launch code?",
        ["orbit-9921-x", "orbit-9921"],
        label="fact_deep_middle",
    ),
    TestCase(
        "What does Rohit prefer over smartwatches?",
        ["analog watch", "analog watches"],
        label="fact_near_end",
    ),
    TestCase(
        "What is the final verification number?",
        ["558391"],
        label="fact_end",
    ),
    TestCase(
        "What was the Mars access password?",
        [],
        negative=True,
        label="hallucination_guard",
    ),
    TestCase(
        "List all special memory facts hidden in this document, in the order they appear.",
        [
            "blue tiger",
            "84721",
            "jonathan miles",
            "orbit-9921",
            "analog watch",
            "558391",
        ],
        label="cross_reference",
    ),
]


def load_config() -> dict:
    if DEFAULT_CONFIG.is_file():
        return json.loads(DEFAULT_CONFIG.read_text(encoding="utf-8"))
    return {
        "model": "roPac",
        "base_model": "qwen2.5-coder:latest",
        "ollama_base_url": "http://localhost:11434/v1",
    }


def resolve_model(name: str | None, cfg: dict) -> str:
    if name:
        return name
    return str(cfg.get("base_model") or cfg.get("model") or "qwen2.5-coder:latest")


def generate_context_file(
    output_path: Path,
    *,
    num_sections: int = 2000,
    paragraphs_per_section: tuple[int, int] = (2, 4),
    target_chars: int = 380_000,
    seed: int = 42,
) -> dict:
    try:
        from faker import Faker
    except ImportError:
        print("Install faker: pip install faker", file=sys.stderr)
        sys.exit(1)

    fake = Faker()
    Faker.seed(seed)

    # Insert facts at proportional positions through the final document.
    fact_positions = [0.02, 0.50, 0.72, 0.92, 0.98]
    pending_facts: list[tuple[int, str, str]] = [
        (int(target_chars * pos), fact, region)
        for pos, (fact, region) in zip(fact_positions, SPECIAL_MEMORIES)
    ]
    next_fact = 0

    lines: list[str] = [
        "# Context stress-test document",
        f"# Target size: ~{target_chars:,} chars | planned sections: up to {num_sections}",
        "",
    ]

    def current_size() -> int:
        return len("\n".join(lines))

    for section_i in range(num_sections):
        lines.append(f"## Section {section_i + 1:04d}")
        lines.append("")

        while next_fact < len(pending_facts) and current_size() >= pending_facts[next_fact][0]:
            _pos, fact, region = pending_facts[next_fact]
            lines.append(f"[SPECIAL_MEMORY:{region}] {fact}")
            lines.append("")
            next_fact += 1

        para_count = fake.random_int(paragraphs_per_section[0], paragraphs_per_section[1])
        for _ in range(para_count):
            lines.append(fake.paragraph(nb_sentences=fake.random_int(4, 8)))
            lines.append("")

        if current_size() >= target_chars:
            break

    while next_fact < len(pending_facts):
        _pos, fact, region = pending_facts[next_fact]
        lines.append(f"## Section {len([l for l in lines if l.startswith('## Section')]) + 1:04d}")
        lines.append("")
        lines.append(f"[SPECIAL_MEMORY:{region}] {fact}")
        lines.append("")
        next_fact += 1

    text = "\n".join(lines).strip() + "\n"
    output_path.write_text(text, encoding="utf-8")

    stats = {
        "path": str(output_path),
        "chars": len(text),
        "lines": text.count("\n") + 1,
        "sections": sum(1 for line in lines if line.startswith("## Section")),
        "facts_inserted": sum(1 for fact, _ in SPECIAL_MEMORIES if fact in text),
        "approx_tokens": len(text) // 4,
    }
    return stats


def ask_model(
    model: str,
    document: str,
    question: str,
    *,
    base_url: str,
    max_tokens: int = 1024,
) -> str:
    from openai import OpenAI

    client = OpenAI(base_url=base_url, api_key="ollama")
    system = (
        "You are a precise document analyst. Answer ONLY using the document below. "
        "If the answer is not in the document, say clearly that the information "
        "is not in the document. Do not invent facts."
    )
    user = f"DOCUMENT:\n\n{document}\n\n---\n\nQUESTION: {question}"
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        temperature=0.1,
        max_tokens=max_tokens,
    )
    content = response.choices[0].message.content or ""
    return content.strip()


def score_answer(case: TestCase, answer: str) -> tuple[bool, str]:
    lower = answer.lower()
    if case.negative:
        invented_mars_password = bool(re.search(r"mars.{0,40}password.{0,20}[a-z0-9-]{4,}", lower))
        denies = any(p in lower for p in NEGATIVE_PHRASES)
        ok = denies and not invented_mars_password
        detail = "correctly denied" if ok else "may have hallucinated"
        return ok, detail

    if case.label == "cross_reference":
        hits = sum(1 for kw in case.expected_keywords if kw in lower)
        ok = hits >= 5
        return ok, f"recalled {hits}/{len(case.expected_keywords)} facts"

    ok = any(kw in lower for kw in case.expected_keywords)
    detail = "matched" if ok else f"missing {case.expected_keywords}"
    return ok, detail


def run_benchmark(
    file_path: Path,
    *,
    model: str,
    base_url: str,
    max_doc_chars: int | None = None,
) -> list[dict]:
    document = file_path.read_text(encoding="utf-8")
    if max_doc_chars and len(document) > max_doc_chars:
        print(
            f"Warning: truncating document {len(document):,} → {max_doc_chars:,} chars "
            f"for this test run.",
        )
        document = document[:max_doc_chars]

    print(f"\nModel: {model}")
    print(f"Document: {len(document):,} chars (~{len(document) // 4:,} tokens est.)")
    print(f"Ollama: {base_url}\n")
    print(f"{'TEST':<22} {'PASS':<6} DETAIL")
    print("-" * 70)

    results: list[dict] = []
    for case in TEST_CASES:
        t0 = time.perf_counter()
        try:
            answer = ask_model(model, document, case.question, base_url=base_url)
        except Exception as e:
            answer = f"ERROR: {e}"
        elapsed = time.perf_counter() - t0
        passed, detail = score_answer(case, answer) if not answer.startswith("ERROR:") else (False, answer)
        mark = "PASS" if passed else "FAIL"
        print(f"{case.label:<22} {mark:<6} {detail} ({elapsed:.1f}s)")
        results.append(
            {
                "label": case.label,
                "question": case.question,
                "passed": passed,
                "detail": detail,
                "elapsed_s": round(elapsed, 2),
                "answer_preview": answer[:300],
            }
        )

    passed = sum(1 for r in results if r["passed"])
    print("-" * 70)
    print(f"Score: {passed}/{len(results)} passed\n")
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate and test long-context retrieval.")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Output file path (default: {DEFAULT_OUTPUT.name})",
    )
    parser.add_argument("--sections", type=int, default=2000, help="Number of sections")
    parser.add_argument(
        "--target-chars",
        type=int,
        default=380_000,
        help="Approximate target file size in characters (~100k tokens)",
    )
    parser.add_argument("--seed", type=int, default=42, help="Faker random seed")
    parser.add_argument("--model", help="Ollama model tag (default: from config.json)")
    parser.add_argument(
        "--max-doc-chars",
        type=int,
        default=None,
        help="Truncate document to N chars when testing (optional)",
    )
    parser.add_argument("--generate-only", action="store_true", help="Only generate the file")
    parser.add_argument("--test-only", action="store_true", help="Only run tests on existing file")
    args = parser.parse_args()

    cfg = load_config()
    model = resolve_model(args.model, cfg)
    base_url = str(cfg.get("ollama_base_url") or "http://localhost:11434/v1")

    if not args.test_only:
        print(f"Generating {args.output} …")
        stats = generate_context_file(
            args.output,
            num_sections=args.sections,
            target_chars=args.target_chars,
            seed=args.seed,
        )
        print(
            f"Wrote {stats['path']}\n"
            f"  chars:   {stats['chars']:,}\n"
            f"  tokens:  ~{stats['approx_tokens']:,} (estimate)\n"
            f"  sections:{stats['sections']}\n"
            f"  facts:   {stats['facts_inserted']}/{len(SPECIAL_MEMORIES)}"
        )

    if args.generate_only:
        return

    if not args.output.is_file():
        print(f"File not found: {args.output}", file=sys.stderr)
        sys.exit(1)

    results = run_benchmark(
        args.output,
        model=model,
        base_url=base_url,
        max_doc_chars=args.max_doc_chars,
    )
    report_path = args.output.with_suffix(".results.json")
    report_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"Results saved: {report_path}")


if __name__ == "__main__":
    main()
