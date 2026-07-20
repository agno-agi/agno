"""The improvement loop: sample, export, train, re-measure, diff.

One `ImprovementLoop` closes the four steps that turn a verified environment into a
better model. It composes shipped pieces -- `run_rollouts`, `learning_zone()`,
`to_sft_jsonl`, `diff` -- with a `Trainer`, and owns only the bookkeeping between them:
which model generates the data, which file gets trained on, and what the before/after
actually compared.

This is **expert iteration** (rejection-sampling fine-tuning). It amplifies what the
base model already does sometimes, and it can saturate. A rising pass rate is progress
on *this verifier*, which is why `audit_scorer` exists. The loop trains on the same
tasks it re-measures, so part of any gain is memorization of those tasks: for a
generalization claim, measure on held-out tasks with
`run_rollouts(env, tasks=held_out, model=trainer.as_model(ckpt))`. And at small n the
numbers are noisy -- a pass rate over n scored attempts has standard error about
sqrt(p(1-p)/n), so at 3 tasks and k=8 a swing of 0.10 is noise and one flipped attempt
prints as a per-task regression. Prefer 20 or more tasks and k of at least 8 before
trusting a delta.
"""

import asyncio
import hashlib
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

from agno.agent import Agent
from agno.environments.environment import Environment
from agno.environments.exporters import ExportReport, ato_sft_jsonl
from agno.environments.exporters._validate import MAX_CONVERSATIONS, MAX_DATASET_BYTES
from agno.environments.runner import EnvironmentDiff, EnvironmentRunResult, arun_rollouts
from agno.scorer import FingerprintError, Scorer
from agno.trainers.base import Checkpoint, Trainer, TrainOn, TrainResult
from agno.utils.log import log_warning

_ConvergedReason = Literal["saturated", "all_failing", "not_exportable", "baseline_unscored"]


@dataclass(frozen=True)
class RewardHackReport:
    """One round's train-scorer vs audit-scorer reading of the same tuned rollout.

    There is deliberately no verdict field. Every threshold is task-relative, and the
    diagnostic signal is the gap *widening* round over round -- train rising while the
    audit stalls -- not a single round's offset. A stricter audit scorer sitting
    uniformly lower from round one is calibration, not hacking. Read the series across
    reports; agno does not decide for you.
    """

    round: int
    train_pass_rate: Optional[float]
    audit_pass_rate: Optional[float]
    gap: Optional[float]  # train - audit

    def _to_dict(self) -> Dict[str, Any]:
        return {
            "round": self.round,
            "train_pass_rate": self.train_pass_rate,
            "audit_pass_rate": self.audit_pass_rate,
            "gap": self.gap,
        }


@dataclass
class IterationReport:
    """What one round did, including the rounds that trained nothing.

    On a converged or failed round every tuned field is None. No number is fabricated
    for a model that never existed.
    """

    round: int  # 1-based
    baseline_pass_rate: Optional[float]  # None only if the baseline had zero scored attempts
    tuned_pass_rate: Optional[float]
    diff: Optional[EnvironmentDiff]
    env_fingerprint: str  # non-None, guaranteed by the pre-flight
    baseline_policy_fingerprint: str
    tuned_policy_fingerprint: Optional[str]
    dataset_path: Optional[str]  # the round's cumulative training file
    dataset_digest: Optional[str]  # sha256 of that file
    checkpoint: Optional[Checkpoint]
    export_report: ExportReport  # THIS round's fresh export; its counters explain empty rounds
    train_result: Optional[TrainResult]
    reward_hack: Optional[RewardHackReport] = None
    audit_scorer_digest: Optional[str] = None
    converged: bool = False
    converged_reason: Optional[_ConvergedReason] = None

    def to_dict(self) -> Dict[str, Any]:
        """A json-ready report. Byte-stable under `json.dumps(..., sort_keys=True)` for
        two identical runs sharing an explicit workdir: nothing here carries a timing,
        a uuid, or an object address."""
        checkpoint = None
        if self.checkpoint is not None:
            checkpoint = {
                "ref": self.checkpoint.ref,
                "base_model": self.checkpoint.base_model,
                "dataset_digest": self.checkpoint.dataset_digest,
                "hyperparams": dict(self.checkpoint.hyperparams),
            }
        train_result = None
        if self.train_result is not None:
            train_result = {
                "status": self.train_result.status.value,
                "step_metrics": list(self.train_result.step_metrics),
                "error": self.train_result.error,
                "checkpoint_ref": self.train_result.checkpoint.ref if self.train_result.checkpoint else None,
            }
        return {
            "round": self.round,
            "baseline_pass_rate": self.baseline_pass_rate,
            "tuned_pass_rate": self.tuned_pass_rate,
            "diff": self.diff.to_dict() if self.diff is not None else None,
            "env_fingerprint": self.env_fingerprint,
            "baseline_policy_fingerprint": self.baseline_policy_fingerprint,
            "tuned_policy_fingerprint": self.tuned_policy_fingerprint,
            "dataset_path": self.dataset_path,
            "dataset_digest": self.dataset_digest,
            "checkpoint": checkpoint,
            "export_report": {
                "n_written": self.export_report.n_written,
                "n_skipped_failed": self.export_report.n_skipped_failed,
                "n_skipped_tool_runs": self.export_report.n_skipped_tool_runs,
                "n_skipped_limit_hit": self.export_report.n_skipped_limit_hit,
                "n_skipped_no_text": self.export_report.n_skipped_no_text,
                "n_dropped_over_cap": self.export_report.n_dropped_over_cap,
            },
            "train_result": train_result,
            "reward_hack": self.reward_hack._to_dict() if self.reward_hack is not None else None,
            "audit_scorer_digest": self.audit_scorer_digest,
            "converged": self.converged,
            "converged_reason": self.converged_reason,
        }


@dataclass
class ImprovementLoop:
    """Run an environment against a trainer until it stops getting better.

    The environment supplies the agent *design* -- instructions, tools, tasks, scorer.
    The trainer supplies the *model*. The loop overrides the model per rollout, so
    baseline and tuned share one agent design and one environment and the only thing
    that changes is the weights. That is what makes the before/after apples-to-apples:
    same `env_fingerprint`, different `policy_fingerprint`.

    The env agent's own declared model is a don't-care here -- it is always overridden.
    Build the env agent model-less, or expect its model ignored.
    """

    env: Environment
    trainer: Trainer
    k: int = 8
    audit_scorer: Optional[Scorer] = None
    workdir: Optional[Path] = None

    _round: int = field(default=0, init=False)
    _last_tuned_result: Optional[EnvironmentRunResult] = field(default=None, init=False)
    _rows: List[str] = field(default_factory=list, init=False)
    _warned_output_schema: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if self.workdir is None:
            # Round datasets are provenance; keep them on disk for the loop's life.
            self.workdir = Path(tempfile.mkdtemp(prefix="agno-improvement-"))
        else:
            self.workdir = Path(self.workdir)
            self.workdir.mkdir(parents=True, exist_ok=True)

    # -- doors ------------------------------------------------------------------

    def step(self) -> IterationReport:
        """One round: generate a dataset, train on it, re-measure. Sync door."""
        _refuse_running_loop("step", "astep")
        return asyncio.run(self.astep())

    def run(self, rounds: int = 1) -> List[IterationReport]:
        """Repeated `step()`, stopping early on convergence or a failed fit. Sync door."""
        _refuse_running_loop("run", "arun")
        return asyncio.run(self.arun(rounds=rounds))

    async def arun(self, rounds: int = 1) -> List[IterationReport]:
        reports: List[IterationReport] = []
        for _ in range(rounds):
            report = await self.astep()
            reports.append(report)
            if report.converged:
                break
            if report.train_result is not None and report.train_result.checkpoint is None:
                break  # a fit that produced nothing: the next round would train on the same data
        return reports

    # -- the round ---------------------------------------------------------------

    async def astep(self) -> IterationReport:
        self._round += 1
        round_number = self._round

        # 1. Baseline. Round 1 samples the model about to be trained -- not the env
        #    agent's declared model, which would measure the wrong thing. Later rounds
        #    reuse the previous round's tuned result: it is the same policy, already
        #    measured, and re-rolling it would pay twice to print sampling noise as
        #    disagreement.
        if self._last_tuned_result is not None:
            baseline = self._last_tuned_result
        else:
            baseline_model = await self.trainer.abase_as_model()
            baseline = await arun_rollouts(self.env, k=self.k, model=baseline_model)

        # 2. Pre-flight, before any spend.
        self._preflight(baseline, round_number)
        env_fingerprint = str(baseline.env_fingerprint)
        baseline_policy_fingerprint = str(baseline.policy_fingerprint)
        audit_digest = self._audit_digest()

        if baseline.pass_rate is None:
            # Zero scored attempts is a scorer outage or an error storm, not
            # convergence -- but there is nothing to train on either way.
            return IterationReport(
                round=round_number,
                baseline_pass_rate=None,
                tuned_pass_rate=None,
                diff=None,
                env_fingerprint=env_fingerprint,
                baseline_policy_fingerprint=baseline_policy_fingerprint,
                tuned_policy_fingerprint=None,
                dataset_path=None,
                dataset_digest=None,
                checkpoint=None,
                export_report=ExportReport(),
                train_result=None,
                audit_scorer_digest=audit_digest,
                converged=True,
                converged_reason="baseline_unscored",
            )

        # 3. Fresh export of this round's learning zone.
        assert self.workdir is not None
        fresh_path = self.workdir / f"round_{round_number}_new.jsonl"
        export_report = await ato_sft_jsonl(baseline.learning_zone(), fresh_path)

        if export_report.n_written == 0:
            return IterationReport(
                round=round_number,
                baseline_pass_rate=baseline.pass_rate,
                tuned_pass_rate=None,
                diff=None,
                env_fingerprint=env_fingerprint,
                baseline_policy_fingerprint=baseline_policy_fingerprint,
                tuned_policy_fingerprint=None,
                dataset_path=None,
                dataset_digest=None,
                checkpoint=None,
                export_report=export_report,
                train_result=None,
                audit_scorer_digest=audit_digest,
                converged=True,
                converged_reason=_converged_reason_for(baseline.pass_rate),
            )

        # 4. Cumulative dataset. `fit` retrains the pristine base every round, and the
        #    learning zone systematically excludes tasks the previous round mastered --
        #    so training on this round's rows alone would forget them.
        dataset_path, cumulative_rows = self._write_cumulative(fresh_path, round_number)
        dataset_digest = hashlib.sha256(dataset_path.read_bytes()).hexdigest()

        # 5. Train.
        train_result = await self.trainer.afit(dataset_path, train_on=TrainOn.LAST_ASSISTANT)
        if train_result.checkpoint is None:
            # Retaining this round's rows would double them: a failed fit leaves no
            # tuned policy, so a second bare step() re-rolls the same base and exports
            # the same learning zone again.
            return IterationReport(
                round=round_number,
                baseline_pass_rate=baseline.pass_rate,
                tuned_pass_rate=None,
                diff=None,
                env_fingerprint=env_fingerprint,
                baseline_policy_fingerprint=baseline_policy_fingerprint,
                tuned_policy_fingerprint=None,
                dataset_path=str(dataset_path),
                dataset_digest=dataset_digest,
                checkpoint=None,
                export_report=export_report,
                train_result=train_result,
                audit_scorer_digest=audit_digest,
            )

        # The rows are kept only once a checkpoint exists to show for them.
        self._rows = cumulative_rows

        # 6. Measure what was paid for -- including a PARTIAL run's recovery checkpoint.
        tuned_model = await self.trainer.aas_model(train_result.checkpoint)
        tuned = await arun_rollouts(self.env, k=self.k, model=tuned_model)
        diff = tuned.diff(baseline)
        reward_hack = await self._audit(tuned, round_number)
        self._last_tuned_result = tuned

        return IterationReport(
            round=round_number,
            baseline_pass_rate=baseline.pass_rate,
            tuned_pass_rate=tuned.pass_rate,
            diff=diff,
            env_fingerprint=env_fingerprint,
            baseline_policy_fingerprint=baseline_policy_fingerprint,
            tuned_policy_fingerprint=tuned.policy_fingerprint,
            dataset_path=str(dataset_path),
            dataset_digest=dataset_digest,
            checkpoint=train_result.checkpoint,
            export_report=export_report,
            train_result=train_result,
            reward_hack=reward_hack,
            audit_scorer_digest=audit_digest,
        )

    # -- internals ---------------------------------------------------------------

    def _preflight(self, baseline: EnvironmentRunResult, round_number: int) -> None:
        """Fail here, not after a paid fine-tune.

        A None env fingerprint makes `diff()` raise, and a None policy fingerprint
        silently forces `policy_changed=True` -- both make the round unmeasurable, so
        neither is worth training through.
        """
        if baseline.env_fingerprint is None:
            raise FingerprintError(
                "env_fingerprint is None, so this round could not be measured even if it trained: "
                "the environment could not be digested (most often a scorer whose source is not "
                "retrievable -- give it a digestible source, e.g. a module-level function rather "
                "than one built at runtime). Refusing to train."
            )
        if baseline.policy_fingerprint is None:
            raise FingerprintError(
                "policy_fingerprint is None, so baseline and tuned cannot be told apart: "
                "the baseline model produced no identity payload (an agent with no model, or a "
                "model whose identity could not be built). Refusing to train."
            )
        if round_number == 1 and not self._warned_output_schema:
            self._warned_output_schema = True
            try:
                # Resolves a factory too: the isolation-recommended shape must not be
                # the one shape that silently skips the warning.
                agent: Optional[Agent] = self.env._source_agent()
            except Exception:
                agent = None
            if agent is not None and getattr(agent, "output_schema", None) is not None:
                log_warning(
                    "ImprovementLoop: the environment agent declares an output_schema, so the "
                    "exported dataset contains raw JSON text as the training target. Fine-tuning "
                    "on JSON strings is rarely what you want; text-answer tasks are the intended fit."
                )

    def _write_cumulative(self, fresh_path: Path, round_number: int) -> Tuple[Path, List[str]]:
        """Every retained row from rounds 1..n, newest first, capped by the validator.

        Returns the file and the rows it holds; the caller decides whether to keep
        them, so a round whose fit produced nothing does not leave its rows behind to
        be exported a second time.
        """
        assert self.workdir is not None
        fresh_lines = [line for line in fresh_path.read_text(encoding="utf-8").split("\n") if line.strip()]
        rows = fresh_lines + self._rows

        kept: List[str] = []
        total_bytes = 0
        for line in rows:
            line_bytes = len(line.encode("utf-8")) + 1
            if len(kept) >= MAX_CONVERSATIONS or total_bytes + line_bytes > MAX_DATASET_BYTES:
                break
            kept.append(line)
            total_bytes += line_bytes
        dropped = len(rows) - len(kept)
        if dropped:
            log_warning(
                f"ImprovementLoop round {round_number}: cumulative dataset hit the validator caps "
                f"({MAX_CONVERSATIONS} conversations / {MAX_DATASET_BYTES} bytes); dropped the "
                f"{dropped} oldest row(s)."
            )

        dataset_path = self.workdir / f"round_{round_number}.jsonl"
        dataset_path.write_text("\n".join(kept) + "\n", encoding="utf-8")
        return dataset_path, kept

    def _audit_digest(self) -> Optional[str]:
        if self.audit_scorer is None:
            return None
        digest = getattr(self.audit_scorer, "digest", None)
        if digest is None or not callable(digest):
            log_warning(f"audit_scorer_digest degraded to None: {type(self.audit_scorer).__name__} has no digest()")
            return None
        try:
            return str(digest())
        except FingerprintError as exc:
            log_warning(f"audit_scorer_digest degraded to None: {exc}")
            return None

    async def _audit(self, tuned: EnvironmentRunResult, round_number: int) -> Optional[RewardHackReport]:
        """Re-score the tuned rollout's scored attempts with the held-out verifier.

        Deliberately the measurement rollout and not the exported rows: those all passed
        the train scorer by construction, which would pin `train_pass_rate` at 1.0 and
        destroy the signal.
        """
        if self.audit_scorer is None:
            return None
        n_audited = 0
        n_passed = 0
        for task_result in tuned.task_results:
            for attempt in task_result.attempts:
                if attempt.score is None or attempt.run is None:
                    continue
                try:
                    audit_score = await self.audit_scorer.ascore(attempt.run, task_result.task.expected)
                except Exception as exc:
                    # An audit failure is not a verdict: leave it out of both sides of
                    # the rate rather than counting it as a fail.
                    log_warning(f"audit_scorer raised on {task_result.task.id}: {type(exc).__name__}: {exc}")
                    continue
                n_audited += 1
                if audit_score.passed:
                    n_passed += 1
        audit_pass_rate = (n_passed / n_audited) if n_audited else None
        train_pass_rate = tuned.pass_rate
        gap = None if (audit_pass_rate is None or train_pass_rate is None) else train_pass_rate - audit_pass_rate
        return RewardHackReport(
            round=round_number,
            train_pass_rate=train_pass_rate,
            audit_pass_rate=audit_pass_rate,
            gap=gap,
        )


def _converged_reason_for(pass_rate: float) -> _ConvergedReason:
    if pass_rate >= 1.0:
        return "saturated"
    if pass_rate <= 0.0:
        return "all_failing"
    # A non-empty learning zone whose passing attempts were all tool-bearing,
    # limit-hit, or textless: verifiable, but nothing the SFT format can carry.
    return "not_exportable"


def _refuse_running_loop(sync_name: str, async_name: str) -> None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return
    raise RuntimeError(
        f"ImprovementLoop.{sync_name} cannot be called from a running event loop; await loop.{async_name}() instead"
    )
