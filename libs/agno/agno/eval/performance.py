import asyncio
import gc
import tracemalloc
from dataclasses import dataclass, field
from os import getenv
from typing import TYPE_CHECKING, Callable, List, Optional
from uuid import uuid4

from agno.api.schemas.evals import EvalType
from agno.eval.utils import async_log_eval_run, log_eval_run, store_result_in_file
from agno.utils.log import logger
from agno.utils.timer import Timer

if TYPE_CHECKING:
    from rich.console import Console


@dataclass
class PerformanceResult:
    """
    Holds run-time and memory-usage statistics.
    In addition to average, min, max, std dev, we add median and percentile metrics
    for a more robust understanding.
    """

    # Run time performance in seconds
    run_times: List[float] = field(default_factory=list)
    avg_run_time: float = field(init=False)
    min_run_time: float = field(init=False)
    max_run_time: float = field(init=False)
    std_dev_run_time: float = field(init=False)
    median_run_time: float = field(init=False)
    p95_run_time: float = field(init=False)

    # Memory performance in MiB
    memory_usages: List[float] = field(default_factory=list)
    avg_memory_usage: float = field(init=False)
    min_memory_usage: float = field(init=False)
    max_memory_usage: float = field(init=False)
    std_dev_memory_usage: float = field(init=False)
    median_memory_usage: float = field(init=False)
    p95_memory_usage: float = field(init=False)

    def __post_init__(self):
        self.compute_stats()

    def compute_stats(self):
        """Compute a variety of statistics for both runtime and memory usage."""
        import statistics

        def safe_stats(data: List[float]):
            """Compute stats for a non-empty list of floats."""
            data_sorted = sorted(data)  # ensure data is sorted for correct percentile
            avg = statistics.mean(data_sorted)
            mn = data_sorted[0]
            mx = data_sorted[-1]
            std = statistics.stdev(data_sorted) if len(data_sorted) > 1 else 0
            med = statistics.median(data_sorted)
            # For 95th percentile, use statistics.quantiles
            p95 = statistics.quantiles(data_sorted, n=100)[94] if len(data_sorted) > 1 else 0
            return avg, mn, mx, std, med, p95

        # Populate runtime stats
        if self.run_times:
            (
                self.avg_run_time,
                self.min_run_time,
                self.max_run_time,
                self.std_dev_run_time,
                self.median_run_time,
                self.p95_run_time,
            ) = safe_stats(self.run_times)
        else:
            self.avg_run_time = 0
            self.min_run_time = 0
            self.max_run_time = 0
            self.std_dev_run_time = 0
            self.median_run_time = 0
            self.p95_run_time = 0

        # Populate memory stats
        if self.memory_usages:
            (
                self.avg_memory_usage,
                self.min_memory_usage,
                self.max_memory_usage,
                self.std_dev_memory_usage,
                self.median_memory_usage,
                self.p95_memory_usage,
            ) = safe_stats(self.memory_usages)
        else:
            self.avg_memory_usage = 0
            self.min_memory_usage = 0
            self.max_memory_usage = 0
            self.std_dev_memory_usage = 0
            self.median_memory_usage = 0
            self.p95_memory_usage = 0

    def print_summary(self, console: Optional["Console"] = None):
        """
        Prints a summary table of the computed stats.
        """
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        # Create performance table
        perf_table = Table(title="Performance Summary", show_header=True, header_style="bold magenta")
        perf_table.add_column("Metric", style="cyan")
        perf_table.add_column("Time (seconds)", style="green")
        perf_table.add_column("Memory (MiB)", style="yellow")

        # Add rows
        perf_table.add_row("Average", f"{self.avg_run_time:.6f}", f"{self.avg_memory_usage:.6f}")
        perf_table.add_row("Minimum", f"{self.min_run_time:.6f}", f"{self.min_memory_usage:.6f}")
        perf_table.add_row("Maximum", f"{self.max_run_time:.6f}", f"{self.max_memory_usage:.6f}")
        perf_table.add_row("Std Dev", f"{self.std_dev_run_time:.6f}", f"{self.std_dev_memory_usage:.6f}")
        perf_table.add_row("Median", f"{self.median_run_time:.6f}", f"{self.median_memory_usage:.6f}")
        perf_table.add_row("95th %ile", f"{self.p95_run_time:.6f}", f"{self.p95_memory_usage:.6f}")

        console.print(perf_table)

    def print_results(self, console: Optional["Console"] = None):
        """
        Prints individual run results in tabular form.
        """
        from rich.console import Console
        from rich.table import Table

        if console is None:
            console = Console()

        # Create runs table
        results_table = Table(title="Individual Runs", show_header=True, header_style="bold magenta")
        results_table.add_column("Run #", style="cyan")
        results_table.add_column("Time (seconds)", style="green")
        results_table.add_column("Memory (MiB)", style="yellow")

        # Add rows
        for i in range(len(self.run_times)):
            results_table.add_row(str(i + 1), f"{self.run_times[i]:.6f}", f"{self.memory_usages[i]:.6f}")

        console.print(results_table)


@dataclass
class PerformanceEval:
    """
    Evaluate the performance of a function by measuring run time and peak memory usage.

    - Warm-up runs are included to avoid measuring overhead on the first execution(s).
    - Debug mode can show top memory allocations using tracemalloc snapshots.
    - Optionally, you can enable cProfile for CPU profiling stats.
    """

    # Function to evaluate
    func: Callable
    measure_runtime: bool = True
    measure_memory: bool = True

    # Evaluation name
    name: Optional[str] = None
    # Evaluation UUID
    eval_id: str = field(default_factory=lambda: str(uuid4()))
    # Number of warm-up runs (not included in final stats)
    warmup_runs: int = 10
    # Number of measured iterations
    num_iterations: int = 50
    # Result of the evaluation
    result: Optional[PerformanceResult] = None

    # Print summary of results
    print_summary: bool = False
    # Print detailed results
    print_results: bool = False
    # If set, results will be saved in the given file path
    file_path_to_save_results: Optional[str] = None
    # Enable debug logs
    debug_mode: bool = getenv("AGNO_DEBUG", "false").lower() == "true"
    # Log the results to the Agno platform. On by default.
    monitoring: bool = getenv("AGNO_MONITOR", "true").lower() == "true"

    def _measure_time(self) -> float:
        """Measure execution time for a single run."""
        timer = Timer()

        timer.start()
        self.func()
        timer.stop()

        return timer.elapsed

    async def _async_measure_time(self) -> float:
        """Measure execution time for a single run of the contextual async function."""
        timer = Timer()

        timer.start()
        await self.func()
        timer.stop()

        return timer.elapsed

    def _measure_memory(self, baseline: float) -> float:
        """
        Measures peak memory usage using tracemalloc.
        Subtracts the provided 'baseline' to compute an adjusted usage.
        """

        # Clear memory before measurement
        gc.collect()
        # Start tracing memory
        tracemalloc.start()

        self.func()

        # Get peak memory usage
        current, peak = tracemalloc.get_traced_memory()
        # Stop tracing memory
        tracemalloc.stop()

        # Convert to MiB and subtract baseline
        peak_mib = peak / 1024 / 1024
        adjusted_usage = max(0, peak_mib - baseline)

        if self.debug_mode:
            logger.debug(f"[DEBUG] Raw peak usage: {peak_mib:.6f} MiB, Adjusted: {adjusted_usage:.6f} MiB")
        return adjusted_usage

    def _parse_eval_run_data(self) -> dict:
        """Parse the evaluation result into a dictionary with the data we want for monitoring."""
        if self.result is None:
            return {}

        return {
            "result": {
                "avg_run_time": self.result.avg_run_time,
                "min_run_time": self.result.min_run_time,
                "max_run_time": self.result.max_run_time,
                "std_dev_run_time": self.result.std_dev_run_time,
                "median_run_time": self.result.median_run_time,
                "p95_run_time": self.result.p95_run_time,
                "avg_memory_usage": self.result.avg_memory_usage,
                "min_memory_usage": self.result.min_memory_usage,
                "max_memory_usage": self.result.max_memory_usage,
                "std_dev_memory_usage": self.result.std_dev_memory_usage,
                "median_memory_usage": self.result.median_memory_usage,
                "p95_memory_usage": self.result.p95_memory_usage,
            },
            "runs": [
                {"runtime": runtime, "memory": memory_usage}
                for runtime, memory_usage in zip(self.result.run_times, self.result.memory_usages)
            ],
        }

    async def _async_measure_memory(self, baseline: float) -> float:
        """
        Measures peak memory usage using tracemalloc for async functions.
        Subtracts the provided 'baseline' to compute an adjusted usage.
        """

        # Clear memory before measurement
        gc.collect()
        # Start tracing memory
        tracemalloc.start()

        await self.func()

        # Get peak memory usage
        current, peak = tracemalloc.get_traced_memory()
        # Stop tracing memory
        tracemalloc.stop()

        # Convert to MiB and subtract baseline
        peak_mib = peak / 1024 / 1024
        adjusted_usage = max(0, peak_mib - baseline)

        if self.debug_mode:
            logger.debug(f"[DEBUG] Raw peak usage: {peak_mib:.6f} MiB, Adjusted: {adjusted_usage:.6f} MiB")
        return adjusted_usage

    def _compute_tracemalloc_baseline(self, samples: int = 3) -> float:
        """
        Runs tracemalloc multiple times with an empty function to establish
        a stable average baseline for memory usage in MiB.
        """

        def empty_func():
            return

        results = []
        for _ in range(samples):
            gc.collect()
            tracemalloc.start()
            empty_func()
            _, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            results.append(peak / 1024 / 1024)

        return sum(results) / len(results) if results else 0

    def run(self, *, print_summary: bool = False, print_results: bool = False) -> PerformanceResult:
        """
        Main method to run the performance evaluation.
        1. Do optional warm-up runs.
        2. Measure runtime
        3. Measure memory
        4. Collect results
        5. Save results if requested
        6. Print results as requested
        7. Log results to the Agno platform if requested
        """
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        run_times = []
        memory_usages = []

        logger.debug(f"************ Evaluation Start: {self.eval_id} ************")

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            # 1. Do optional warm-up runs.
            for i in range(self.warmup_runs):
                status = Status(f"Warm-up run {i + 1}/{self.warmup_runs}...", spinner="dots", speed=1.0)
                live_log.update(status)
                self.func()  # Simply run the function without measuring
                status.stop()

            # 2. Measure runtime
            if self.measure_runtime:
                for i in range(self.num_iterations):
                    status = Status(
                        f"Runtime measurement {i + 1}/{self.num_iterations}...",
                        spinner="dots",
                        speed=1.0,
                        refresh_per_second=10,
                    )
                    live_log.update(status)
                    # Measure runtime
                    elapsed_time = self._measure_time()
                    run_times.append(elapsed_time)

                    logger.debug(f"Run {i + 1} - Time taken: {elapsed_time:.6f} seconds")
                    status.stop()

            # 3. Measure memory
            if self.measure_memory:
                # 3.1 Compute memory baseline
                memory_baseline = 0.0
                memory_baseline = self._compute_tracemalloc_baseline()
                logger.debug(f"Computed memory baseline: {memory_baseline:.6f} MiB")

                for i in range(self.num_iterations):
                    status = Status(
                        f"Memory measurement {i + 1}/{self.num_iterations}...",
                        spinner="dots",
                        speed=1.0,
                        refresh_per_second=10,
                    )
                    live_log.update(status)

                    # Measure memory
                    usage = self._measure_memory(memory_baseline)
                    memory_usages.append(usage)
                    logger.debug(f"Run {i + 1} - Memory usage: {usage:.6f} MiB (adjusted)")

                    status.stop()

        # 4. Collect results
        self.result = PerformanceResult(run_times=run_times, memory_usages=memory_usages)

        # 5. Save result to file if requested
        if self.file_path_to_save_results is not None and self.result is not None:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                name=self.name,
                eval_id=self.eval_id,
                result=self.result,
            )

        # 6. Print results if requested
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # 7. Log results to the Agno platform if requested
        if self.monitoring:
            log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=self._parse_eval_run_data(),
                eval_type=EvalType.PERFORMANCE,
                name=self.name if self.name is not None else None,
                evaluated_entity_name=self.func.__name__,
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result

    async def arun(self, *, print_summary: bool = False, print_results: bool = False) -> PerformanceResult:
        """
        Async method to run the performance evaluation of async functions.
        1. Do optional warm-up runs.
        2. Measure runtime
        3. Measure memory
        4. Collect results
        5. Save results if requested
        6. Print results as requested
        7. Log results to the Agno platform if requested
        """
        # Validate the function to evaluate is async.
        if not asyncio.iscoroutinefunction(self.func):
            raise ValueError(
                f"The provided function ({self.func.__name__}) is not async. Use the run() method for sync functions."
            )

        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        run_times = []
        memory_usages = []

        logger.debug(f"************ Evaluation Start: {self.eval_id} ************")

        # Add a spinner while running the evaluations
        console = Console()
        with Live(console=console, transient=True) as live_log:
            # 1. Do optional warm-up runs.
            for i in range(self.warmup_runs):
                status = Status(f"Warm-up run {i + 1}/{self.warmup_runs}...", spinner="dots", speed=1.0)
                live_log.update(status)
                await self.func()  # Simply run the function without measuring
                status.stop()

            # 2. Measure runtime
            if self.measure_runtime:
                for i in range(self.num_iterations):
                    status = Status(
                        f"Runtime measurement {i + 1}/{self.num_iterations}...",
                        spinner="dots",
                        speed=1.0,
                        refresh_per_second=10,
                    )
                    live_log.update(status)
                    # Measure runtime
                    elapsed_time = await self._async_measure_time()
                    run_times.append(elapsed_time)

                    logger.debug(f"Run {i + 1} - Time taken: {elapsed_time:.6f} seconds")
                    status.stop()

            # 3. Measure memory
            if self.measure_memory:
                # 3.1 Compute memory baseline
                memory_baseline = 0.0
                memory_baseline = self._compute_tracemalloc_baseline()
                logger.debug(f"Computed memory baseline: {memory_baseline:.6f} MiB")

                for i in range(self.num_iterations):
                    status = Status(
                        f"Memory measurement {i + 1}/{self.num_iterations}...",
                        spinner="dots",
                        speed=1.0,
                        refresh_per_second=10,
                    )
                    live_log.update(status)

                    # Measure memory
                    usage = await self._async_measure_memory(memory_baseline)
                    memory_usages.append(usage)
                    logger.debug(f"Run {i + 1} - Memory usage: {usage:.6f} MiB (adjusted)")

                    status.stop()

        # 4. Collect results
        self.result = PerformanceResult(run_times=run_times, memory_usages=memory_usages)

        # 5. Save result to file if requested
        if self.file_path_to_save_results is not None and self.result is not None:
            store_result_in_file(
                file_path=self.file_path_to_save_results,
                name=self.name,
                eval_id=self.eval_id,
                result=self.result,
            )

        # 6. Print results if requested
        if self.print_results or print_results:
            self.result.print_results(console)
        if self.print_summary or print_summary:
            self.result.print_summary(console)

        # 7. Log results to the Agno platform if requested
        if self.monitoring:
            await async_log_eval_run(
                run_id=self.eval_id,  # type: ignore
                run_data=self._parse_eval_run_data(),
                eval_type=EvalType.PERFORMANCE,
                name=self.name if self.name is not None else None,
                evaluated_entity_name=self.func.__name__,
            )

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result
