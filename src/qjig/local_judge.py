"""Optional local judge: environment and input-size guards. Never installs, copies or truncates."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .budgets import BudgetLedger
from .contracts import ContractError
from .judge import JudgeResult, build_side_prompts, judge_predicate
from .packets import EvidencePacket
from .providers import RawResponse, ProviderRequest


class EnvironmentUnavailable(Exception):
    def __init__(self, problems: tuple[str, ...]) -> None:
        super().__init__("local judge environment unavailable: " + ", ".join(problems))
        self.problems = problems


class InputTooLarge(Exception):
    def __init__(self, size: int, limit: int) -> None:
        super().__init__(f"local judge input is {size} characters, over the limit of {limit}; it is not truncated")
        self.size, self.limit = size, limit


@dataclass(frozen=True)
class LocalJudgeConfig:
    interpreter: Path | None
    model_dir: Path | None
    max_input_chars: int
    model_label: str

    def __post_init__(self) -> None:
        if type(self.max_input_chars) is not int or self.max_input_chars < 1:
            raise ContractError("max_input_chars must be a positive integer")


@dataclass(frozen=True)
class EnvReport:
    ok: bool
    problems: tuple[str, ...]


def validate_environment(cfg: LocalJudgeConfig) -> EnvReport:
    """Read-only checks of the configured paths. Nothing is executed, created or copied."""
    problems = []
    if cfg.interpreter is None:
        problems.append("interpreter_not_configured")
    elif not cfg.interpreter.is_file():
        problems.append("interpreter_missing")
    elif not os.access(cfg.interpreter, os.X_OK):
        problems.append("interpreter_not_executable")
    if cfg.model_dir is None:
        problems.append("model_dir_not_configured")
    elif not cfg.model_dir.is_dir():
        problems.append("model_dir_missing")
    return EnvReport(not problems, tuple(problems))


class LocalTransport:
    """Adapts a local text-in/text-out runner to the provider transport interface."""

    def __init__(self, runner: Callable[[str], str], label: str) -> None:
        self._runner, self.label = runner, label

    def send(self, request: ProviderRequest) -> RawResponse:
        return RawResponse(200, self._runner(request.prompt), None)  # local usage is not measured here


def run_local_judge(
    ledger: BudgetLedger, cfg: LocalJudgeConfig, runner: Callable[[str], str], question: str, packet: EvidencePacket
) -> JudgeResult:
    report = validate_environment(cfg)
    if not report.ok:
        raise EnvironmentUnavailable(report.problems)
    size = max(len(r.prompt) for r in build_side_prompts(question, packet))
    if size > cfg.max_input_chars:
        raise InputTooLarge(size, cfg.max_input_chars)  # before any journal entry or inference
    label = getattr(runner, "label", "local runner")
    return judge_predicate(ledger, LocalTransport(runner, label), question, packet, provider="local", model=cfg.model_label)
