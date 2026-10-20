"""Run the curator agent on the labeled evaluation set and score it.

Uses the real LLM providers from .env (Gemini, OpenAI, Ollama), with the same
failover, pacing, and daily caps as the worker. Nothing is written to the
database. Each case costs a few model calls, so a full run uses roughly
100 calls; use --tag or --case to run fewer.

Usage, from backend/:
  uv run python -m scripts.eval_curator                 # every case
  uv run python -m scripts.eval_curator --tag injection # only some tags
  uv run python -m scripts.eval_curator --case good-git-bisect --repeat 3

Exits with 1 when any page that should stay out went live, when a case
failed to run, or when accuracy is below --min-accuracy. A JSON report with
every decision and the agent's reason goes to evals/results/ (git-ignored).
"""

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

from app.ai.llm import LLMRouter, providers_from_settings
from app.cache import create_redis
from app.config import settings
from app.curator.evaluation import (
    DEFAULT_CASES,
    Report,
    case_line,
    filter_cases,
    format_report,
    load_eval_set,
    run_case,
)
from app.curator.model import RouterAgentModel
from app.curator.tools import TOOL_SPECS

RESULTS_DIR = Path(__file__).resolve().parents[1] / "evals" / "results"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--file", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--tag", action="append", default=[], help="repeatable")
    parser.add_argument("--case", action="append", default=[], help="repeatable")
    parser.add_argument("--repeat", type=int, default=1, help="runs per case")
    parser.add_argument("--min-accuracy", type=float, default=0.8)
    parser.add_argument("--out", type=Path, help="where to write the JSON report")
    return parser.parse_args(argv)


async def main(args: argparse.Namespace) -> int:
    providers = providers_from_settings(settings)
    if not providers:
        print("No LLM provider configured: set GEMINI_API_KEY, OPENAI_API_KEY, or")
        print("OLLAMA_BASE_URL in .env.")
        return 2
    eval_set = load_eval_set(args.file)
    cases = filter_cases(eval_set.cases, tags=args.tag, ids=args.case)
    if not cases:
        print("No cases match.")
        return 2

    print(
        f"Running {len(cases)} cases x {args.repeat} with "
        f"{', '.join(f'{p.name} ({p.model})' for p in providers)}"
    )
    redis = create_redis(settings.redis_url)
    results = []
    async with httpx.AsyncClient(timeout=60) as http:
        model = RouterAgentModel(LLMRouter(http, redis, providers), http, TOOL_SPECS)
        for case in cases:
            for _ in range(args.repeat):
                result = await run_case(
                    case,
                    model,
                    eval_set.topics,
                    max_turns=settings.curator_max_turns,
                    max_tool_calls=settings.curator_max_tool_calls,
                )
                results.append(result)
                print(case_line(result), flush=True)
    await redis.aclose()

    report = Report(results)
    print()
    print(format_report(report))

    out = args.out or RESULTS_DIR / f"curator-{datetime.now(UTC):%Y%m%d-%H%M%S}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    details = report.to_dict() | {
        "providers": [f"{p.name}:{p.model}" for p in providers],
        "finished_at": datetime.now(UTC).isoformat(),
    }
    out.write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    print(f"\nReport: {out}")

    if report.passed(args.min_accuracy):
        print("PASS")
        return 0
    print(
        f"FAIL (needs no harmful approvals, no errors, accuracy >= {args.min_accuracy:.0%})"
    )
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main(parse_args())))
