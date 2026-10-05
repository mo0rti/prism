"""Fixed end-to-end journey: real agent hosts and a real browser against the Prism board.

    python scripts/e2e/journey.py --tier smoke|full --out <dir> [--steps a,b,...] [--hosts claude,codex]
                                  [--wheel <path>] [--keep-work] [--timeout <seconds>] [--fixtures <dir>]

See scripts/e2e/README.md for what each tier costs and what the report holds.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, str(Path(__file__).resolve().parent))

from prism_e2e import config  # noqa: E402
from prism_e2e.runner import Journey, Options  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="journey.py",
        description="Run the Prism lifecycle journey with real agent hosts and a headless browser, and write a comparable report.",
    )
    parser.add_argument("--tier", required=True, choices=sorted(config.TIERS), help="smoke: Claude Haiku 4.5 and GPT-6 Luna. full: Claude Sonnet 5.5 and GPT-6.1 Sol, both at medium effort.")
    parser.add_argument("--out", required=True, type=Path, help="Folder for the report, transcripts and logs. It must not hold an earlier report.")
    parser.add_argument("--steps", help=f"Comma-separated subset of: {', '.join(config.STEP_IDS)}. Earlier state is seeded from recorded fixtures. Default: every step.")
    parser.add_argument("--hosts", default=",".join(config.HOSTS), help="Comma-separated hosts to use (claude, codex). A step whose fixed host is not listed runs on the first listed host.")
    parser.add_argument("--wheel", type=Path, help="Install this wheel instead of building one from the current tree.")
    parser.add_argument("--keep-work", action="store_true", help="Keep <out>/work (venv, workspace, wheel) after the run.")
    parser.add_argument("--timeout", type=float, default=config.DEFAULT_TIMEOUT_SECONDS, metavar="SECONDS", help="Timeout per host run; the process tree is killed when it passes. Default: %(default)s.")
    parser.add_argument("--fixtures", metavar="DIR", help=f"A fixture set overlaid on the default fixtures and prompts (see README). Default: ${config.FIXTURES_ENV}, else the default set alone.")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        steps = config.parse_steps(args.steps)
        hosts = config.parse_hosts(args.hosts)
        fixtures = config.resolve_fixture_set(args.fixtures)
    except config.ConfigError as error:
        parser.error(str(error))
    out = args.out.resolve()
    if (out / "report.json").exists() or (out / "transcripts").exists():
        parser.error(f"{out} already holds a run. Choose an empty folder.")
    if args.timeout <= 0:
        parser.error("--timeout must be positive.")
    options = Options(tier=args.tier, out=out, steps=steps, hosts=hosts, wheel=args.wheel.resolve() if args.wheel else None, keep_work=args.keep_work, timeout_s=args.timeout, fixtures=fixtures)
    code = Journey(options).run()
    print(f"report: {out / 'report.md'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
