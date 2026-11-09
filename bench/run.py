"""
MXB-Bench command line.

  python -m bench.run --suite routing                 # ~1 s, any OS, no LLM, no OS side effects
  python -m bench.run --suite routing --llm           # also send deferred phrases to the real planner
  python -m bench.run --suite live                    # Windows: drives the real desktop (~3 min)
  python -m bench.run --suite live --llm              # include LLM planner + agent + prompt-injection tasks
  python -m bench.run --suite all --markdown bench/results/latest.md --update-readme

Exit code 1 when --min-precision is not met (used by CI to stop routing regressions).
"""
import argparse
import json
import os
import platform
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
README_START, README_END = "<!-- MXB-BENCH:START -->", "<!-- MXB-BENCH:END -->"


def environment() -> dict:
    from utils.version import __version__
    llm = {}
    try:
        from utils.paths import load_config
        cfg = load_config().get("llm", {})
        llm = {"cloud_model": cfg.get("model"), "local_model": cfg.get("local_model")}
    except Exception:
        pass
    return {"mxb_version": __version__, "date": time.strftime("%Y-%m-%d %H:%M"), "os": platform.platform(),
            "python": platform.python_version(), **llm}


def routing_markdown(main: dict, heldout: dict) -> str:
    m, h = main["summary"], heldout["summary"]
    lines = [
        "### Routing (fast path, no LLM)",
        "",
        "| Metric | Tuned set | Held-out set |",
        "| :--- | ---: | ---: |",
        f"| Cases | {m['cases']} | {h['cases']} |",
        f"| Precision (right action or correct hand-off to the LLM) | {m['precision']}% | {h['precision']}% |",
        f"| Coverage (actionable commands handled without the LLM) | {m['coverage']}% | {h['coverage']}% |",
        f"| Misroutes | {m['misroutes']} | {h['misroutes']} |",
        f"| Decision time p50 / p95 | {m['p50_ms']} / {m['p95_ms']} ms | {h['p50_ms']} / {h['p95_ms']} ms |",
    ]
    if "accuracy_with_llm" in m:
        lines.append(f"| Accuracy with LLM fallback | {m['accuracy_with_llm']}% | {h.get('accuracy_with_llm', '–')}% |")
    lines += ["", "The tuned set was used while fixing the router; the held-out set never was, so it is the honest "
              "estimate for new phrasing."]
    bad = [r for r in heldout["rows"] + main["rows"] if r["outcome"] in ("misroute", "llm_wrong")]
    if bad:
        lines += ["", "Misroutes:"]
        lines += [f"- `{r['phrase']}` → expected `{r['expected']}`, got `{r['got']}` {r['got_target']!r}" for r in bad[:15]]
    return "\n".join(lines)


def brain_markdown(brain: dict) -> str:
    s = brain["summary"]
    lines = [f"### Brain: everyday requests to actions ({s['model']})", "",
             f"**{s['accuracy']}%** of {s['cases']} plans right · {s['fast_path']} handled instantly · "
             f"{s['model_failures']} model failures · planning p50 {s['p50_s']} s, p95 {s['p95_s']} s", "",
             "| Category | Right |", "| :--- | :--- |"]
    for name, c in sorted(brain["categories"].items()):
        lines.append(f"| {name} | {c['passed']}/{c['cases']} |")
    return "\n".join(lines)


def live_markdown(live: dict) -> str:
    if live.get("error"):
        return f"### Live desktop tasks\n\n{live['error']}"
    s = live["summary"]
    lines = ["### Live desktop tasks (Windows)", "",
             f"**{s['passed']}/{s['ran']} passed ({s['success_rate']}%)**, {s['skipped']} skipped, "
             f"median {s['median_seconds']} s per task, {s['confirmations_asked']} confirmations asked.", "",
             "| Category | Passed |", "| :--- | ---: |"]
    for cat, c in sorted(live["categories"].items()):
        lines.append(f"| {cat} | {c['passed']}/{c['ran']} |")
    fails = [r for r in live["rows"] if r["status"] == "fail"]
    if fails:
        lines += ["", "Failures:"] + [f"- `{r['id']}`: {r['detail'][:140]}" for r in fails]
    return "\n".join(lines)


def update_readme(markdown: str, readme: Path = ROOT / "README.md") -> bool:
    text = readme.read_text(encoding="utf-8")
    block = f"{README_START}\n{markdown}\n{README_END}"
    if README_START in text and README_END in text:
        text = re.sub(re.escape(README_START) + r".*?" + re.escape(README_END), lambda _: block, text, flags=re.S)
    else:
        text = text.rstrip() + "\n\n## 📊 MXB-Bench results\n\n" + block + "\n"
    readme.write_text(text, encoding="utf-8")
    return True


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MXB-Bench")
    parser.add_argument("--suite", choices=["routing", "brain", "live", "all"], default="routing")
    parser.add_argument("--model", default="", help="brain suite: local model to test, e.g. qwen3:4b")
    parser.add_argument("--local-only", action="store_true", help="brain suite: ignore the NVIDIA key")
    parser.add_argument("--llm", action="store_true", help="use the real LLM (NVIDIA key or Ollama required)")
    parser.add_argument("--only", default="", help="comma-separated live task id prefixes, e.g. screen,files.read")
    parser.add_argument("--json", dest="json_out", default="")
    parser.add_argument("--markdown", dest="md_out", default="")
    parser.add_argument("--update-readme", action="store_true")
    parser.add_argument("--min-precision", type=float, default=0.0, help="fail if tuned-set precision is lower (0-1)")
    parser.add_argument("--yes", action="store_true", help="don't ask before taking over the desktop")
    parser.add_argument("--keep-sandbox", action="store_true")
    parser.add_argument("--list", action="store_true", help="list live tasks and exit")
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tests._stubs  # noqa: F401  (stand-ins for Windows-only packages)

    if args.list:
        from bench.live import list_tasks
        for task_id, category, requires in list_tasks():
            print(f"{task_id:38} {category:11} {'needs ' + ', '.join(requires) if requires else ''}")
        return 0

    report = {"environment": environment()}
    sections = []
    exit_code = 0

    if args.suite in ("routing", "all"):
        from bench.routing import run_routing
        from bench.routing_cases import CASES, HELDOUT
        main_res = run_routing(use_llm=args.llm, cases=CASES)
        held_res = run_routing(use_llm=args.llm, cases=HELDOUT)
        report["routing"] = {"tuned": main_res, "heldout": held_res}
        sections.append(routing_markdown(main_res, held_res))
        m = main_res["summary"]
        print(f"Routing (tuned):    precision {m['precision']}%  coverage {m['coverage']}%  misroutes {m['misroutes']}  "
              f"p50 {m['p50_ms']} ms")
        h = held_res["summary"]
        print(f"Routing (held-out): precision {h['precision']}%  coverage {h['coverage']}%  misroutes {h['misroutes']}")
        if args.min_precision and m["precision"] < args.min_precision * 100:
            print(f"FAIL: tuned-set precision {m['precision']}% < {args.min_precision * 100:.1f}%")
            exit_code = 1

    if args.suite in ("brain", "all"):
        from bench.brain import run_brain
        brain = run_brain(model=args.model or None, local_only=args.local_only)
        report["brain"] = brain
        sections.append(brain_markdown(brain))
        b = brain["summary"]
        print(f"Brain ({b['model']}): {b['passed']}/{b['cases']} plans right ({b['accuracy']}%), "
              f"{b['fast_path']} by the fast path, {b['model_failures']} model failures, "
              f"planning p50 {b['p50_s']} s, p95 {b['p95_s']} s")
        for row in brain["rows"]:
            if not row["passed"]:
                print(f"   x {row['phrase'][:48]:48} {row['reason']}")

    if args.suite in ("live", "all"):
        from bench.live import LiveHarness
        if sys.platform == "win32" and not args.yes:
            print("The live suite controls your mouse and keyboard for a few minutes and opens a browser tab and Notepad.")
            print("Close Notepad first. Don't touch the PC. Move the mouse to the top-left corner to stop.")
            try:
                input("Press Enter to start (Ctrl+C to cancel)... ")
            except (KeyboardInterrupt, EOFError):
                return 1
        only = [o.strip() for o in args.only.split(",") if o.strip()]
        live = LiveHarness(use_llm=args.llm, keep_sandbox=args.keep_sandbox).run(only=only or None)
        report["live"] = live
        sections.append(live_markdown(live))
        if live.get("summary"):
            s = live["summary"]
            print(f"Live: {s['passed']}/{s['ran']} passed ({s['success_rate']}%), {s['skipped']} skipped")

    env = report["environment"]
    markdown = (f"_MXB {env['mxb_version']} · {env['date']} · {env['os']} · Python {env['python']}_\n\n"
                + "\n\n".join(sections))
    if args.json_out:
        Path(args.json_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json_out).write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.md_out:
        Path(args.md_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md_out).write_text(markdown + "\n", encoding="utf-8")
    if args.update_readme:
        update_readme(markdown)
        print("README.md updated.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
