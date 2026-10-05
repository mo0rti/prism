"""Tiers, steps, the fixed host table and the seeding plan.

Nothing here touches the network, a host or the disk, so the unit tests can
cover it directly.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
E2E_DIR = PACKAGE_DIR.parent
REPO_ROOT = E2E_DIR.parents[1]
PROMPTS_DIR = E2E_DIR / "prompts"
FIXTURES_DIR = E2E_DIR / "fixtures"
# A second recorded set: the feature's API surface declares API work, so the states after
# design-handoff hold the API contract page and the requirement page that links it.
API_WORK_FIXTURES_DIR = E2E_DIR / "fixtures-api-work"
FIXTURES_ENV = "PRISM_E2E_FIXTURES"

FEATURE_ID = "F-001"
HOSTS = ("claude", "codex")
DEFAULT_TIMEOUT_SECONDS = 600


@dataclass(frozen=True)
class HostModel:
    """The model and effort one tier launches a host with.

    ``effort`` is ``None`` when the host has no effort setting for the model;
    no effort flag is passed and none is expected in the transcript.
    """

    model: str
    effort: str | None


# Exact model IDs and effort values come from `claude.exe --help` (effort: low,
# medium, high, xhigh, max) and `codex debug models` (slugs gpt-6-luna and
# gpt-6.1-sol; effort low to max). Claude Haiku 4.5 has no effort setting: its
# session records carry none.
TIERS: dict[str, dict[str, HostModel]] = {
    "smoke": {
        "claude": HostModel("claude-haiku-4-5", None),
        "codex": HostModel("gpt-6-luna", "medium"),
    },
    "full": {
        "claude": HostModel("claude-sonnet-5-5", "medium"),
        "codex": HostModel("gpt-6.1-sol", "medium"),
    },
}

# Human steps run in the browser; agent steps run in a host through MCP.
HUMAN_ACTION_LABELS = {
    "po-handoff": "handoff",
    "design-start": "design start",
    "dev-start": "development start",
}


@dataclass(frozen=True)
class Step:
    id: str
    kind: str  # "agent" or "human"
    host: str | None  # fixed host for an agent step
    status: str  # feature status expected after the step
    owner: str  # feature owner expected after the step
    summary: str  # what the apply prompt calls the preview

    @property
    def is_human(self) -> bool:
        return self.kind == "human"


# The canonical order. Agent steps alternate between the two hosts.
STEPS: tuple[Step, ...] = (
    Step("po-intake", "agent", "claude", "raw", "po", "the po-intake of the pending review-summary folder"),
    Step("ask", "agent", "codex", "raw", "po", "the ask skill adding one question to F-001"),
    Step("po-clarify", "agent", "claude", "raw", "po", "the po-clarify answers for F-001"),
    Step("po-specify", "agent", "codex", "specified", "po", "the po-specify of F-001"),
    Step("po-handoff", "human", None, "ready-for-design", "designer", "the product owner's handoff of F-001"),
    Step("design-start", "human", None, "in-design", "designer", "the design start of F-001"),
    Step("design-clarify", "agent", "claude", "in-design", "designer", "the design-clarify answer for F-001"),
    Step("design-handoff", "agent", "codex", "ready-for-dev", "dev", "the design handoff of F-001"),
    Step("dev-clarify", "agent", "claude", "ready-for-dev", "dev", "the dev-clarify answer for F-001"),
    Step("dev-start", "human", None, "in-dev", "dev", "the development start of F-001"),
    Step("dev-done", "agent", "codex", "done", "none", "the dev-done of F-001 with the delivery evidence in the proposal"),
    Step("feature-reopen", "agent", "claude", "in-dev", "dev", "the reopen of F-001 on the in-dev route"),
)
STEP_IDS = tuple(step.id for step in STEPS)
STEPS_BY_ID = {step.id: step for step in STEPS}


class ConfigError(ValueError):
    pass


def parse_steps(text: str | None) -> list[str]:
    """Selected step IDs in canonical order. ``None`` or an empty string selects every step."""

    if not text:
        return list(STEP_IDS)
    requested = [part.strip() for part in text.split(",") if part.strip()]
    unknown = [part for part in requested if part not in STEPS_BY_ID]
    if unknown:
        raise ConfigError(f"Unknown step {', '.join(unknown)}. Steps: {', '.join(STEP_IDS)}.")
    return [step_id for step_id in STEP_IDS if step_id in requested]


def resolve_fixture_set(value: str | Path | None, environ: dict[str, str] | None = None) -> Path | None:
    """The fixture set to overlay on the default fixtures, or ``None`` for the default set alone.

    ``value`` is the ``--fixtures`` folder; without it the ``PRISM_E2E_FIXTURES`` variable is used. A set holds
    ``<step>/`` folders in the same layout as ``fixtures/`` and, optionally, ``prompts/<step>.txt`` files. A step
    the set does not hold, and a prompt it does not hold, come from the default set.
    """

    text = str(value) if value else (environ if environ is not None else os.environ).get(FIXTURES_ENV, "")
    if not text.strip():
        return None
    path = Path(text).expanduser().resolve()
    if not path.is_dir():
        raise ConfigError(f"The fixture set {path} is not a folder.")
    known = [name for name in STEP_IDS if (path / name).is_dir()]
    prompts = path / "prompts"
    stray = sorted(
        item.name for item in path.iterdir()
        if item.is_dir() and item.name not in STEP_IDS and item.name != "prompts"
    )
    if stray:
        raise ConfigError(f"The fixture set {path} holds folders that are not steps: {', '.join(stray)}. Steps: {', '.join(STEP_IDS)}.")
    if not known and not prompts.is_dir():
        raise ConfigError(f"The fixture set {path} holds no step folder and no prompts folder.")
    if prompts.is_dir():
        unknown = sorted(item.stem for item in prompts.glob("*.txt") if item.stem not in STEPS_BY_ID or STEPS_BY_ID[item.stem].is_human)
        if unknown:
            raise ConfigError(f"The fixture set {path} holds prompts for no agent step: {', '.join(unknown)}.")
    return path


def parse_hosts(text: str | None) -> list[str]:
    requested = [part.strip() for part in (text or ",".join(HOSTS)).split(",") if part.strip()]
    unknown = [part for part in requested if part not in HOSTS]
    if unknown or not requested:
        raise ConfigError(f"--hosts takes a comma-separated list of: {', '.join(HOSTS)}.")
    seen: list[str] = []
    for host in requested:
        if host not in seen:
            seen.append(host)
    return seen


def host_for(step: Step, hosts: list[str]) -> str | None:
    """The fixed table's host for an agent step. When that host is not enabled, the first enabled host runs it."""

    if step.is_human:
        return None
    assert step.host is not None
    return step.host if step.host in hosts else hosts[0]


@dataclass(frozen=True)
class Action:
    """One planned action: run a step, or seed the journey state after a step from the fixtures."""

    kind: str  # "run" or "seed"
    step: str | None  # run: the step; seed: the last step whose state the fixtures reproduce (None: before every step)


def plan_actions(selected: list[str]) -> list[Action]:
    """Order the work for a selection of steps.

    A step runs on the state that the canonical step before it leaves behind.
    When that predecessor is not the step that ran last, the plan seeds the
    state after the predecessor from the recorded fixtures first. A selection
    that starts at the first step needs no seeding.
    """

    actions: list[Action] = []
    current: str | None = None  # the step whose state the workspace holds; None is the baseline
    for step_id in selected:
        index = STEP_IDS.index(step_id)
        predecessor = STEP_IDS[index - 1] if index > 0 else None
        if predecessor != current:
            actions.append(Action("seed", predecessor))
            current = predecessor
        actions.append(Action("run", step_id))
        current = step_id
    return actions
