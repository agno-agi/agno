import gc
import tracemalloc
from dataclasses import asdict, dataclass, field
from os import getenv
from pathlib import Path
from typing import TYPE_CHECKING, Callable, List, Optional
from uuid import uuid4

from agno.utils.log import logger, set_log_level_to_debug, set_log_level_to_info
from agno.utils.timer import Timer

if TYPE_CHECKING:
    from rich.console import Console


@dataclass
class PerfResult:
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
            p95 = statistics.quantiles(data_sorted, n=100)[94]  # 0-based index: 95th percentile
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
class PerfEval:
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
    # Evaluation UUID (autogenerated if not set)
    eval_id: Optional[str] = None

    # Number of warm-up runs (not included in final stats)
    warmup_runs: int = 10
    # Number of measured iterations
    num_iterations: int = 50

    # Result of the evaluation
    result: Optional[PerfResult] = None

    # Print summary of results
    print_summary: bool = False
    # Print detailed results
    print_results: bool = False
    # Save the result to a file
    save_result_to_file: Optional[str] = None

    # Debug mode = True enables debug logs & top memory usage stats
    debug_mode: bool = False

    def set_eval_id(self) -> str:
        """Generates or reuses an evaluation UUID."""
        if self.eval_id is None:
            self.eval_id = str(uuid4())
        logger.debug(f"*********** Evaluation ID: {self.eval_id} ***********")
        return self.eval_id

    def set_debug_mode(self) -> None:
        """Enables debug mode or sets log to info."""
        if self.debug_mode or getenv("AGNO_DEBUG", "false").lower() == "true":
            self.debug_mode = True
            set_log_level_to_debug()
            logger.debug("Debug logs enabled")
        else:
            set_log_level_to_info()

    def _measure_time(self) -> float:
        """Utility method to measure execution time for a single run."""
        # Create a timer
        timer = Timer()
        # Start the timer
        timer.start()
        # Run the function
        self.func()
        # Stop the timer
        timer.stop()
        # Return the elapsed time
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
        # Run the function
        self.func()
        # Get peak memory usage
        current, peak = tracemalloc.get_traced_memory()
        # Stop tracing memory
        tracemalloc.stop()

        # Convert to MiB and subtract baseline
        peak_mib = peak / (1024 * 1024)
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
            results.append(peak / (1024 * 1024))

        return sum(results) / len(results) if results else 0

    def run(self, *, print_summary: bool = False, print_results: bool = False) -> PerfResult:
        """
        Main method to perform the performance evaluation.
        1. Do optional warm-up runs.
        2. Measure runtime
        3. Measure memory
        4. Collect results
        5. Save results if requested
        6. Print results as requested
        """
        from rich.console import Console
        from rich.live import Live
        from rich.status import Status

        # Prepare environment
        self.set_eval_id()
        self.set_debug_mode()
        self.print_results = print_results
        self.print_summary = print_summary

        # Create a console for logging
        console = Console()
        # Initialize lists for run times and memory usages
        run_times = []
        memory_usages = []

        with Live(console=console, transient=True) as live_log:
            # 1. Warm-up runs (not measured)
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
        self.result = PerfResult(run_times=run_times, memory_usages=memory_usages)

        # 5. Save results if requested
        self._save_results()

        # 6. Print results as requested
        if self.print_results and self.result:
            self.result.print_results(console)
        if (self.print_summary or self.print_results) and self.result:
            self.result.print_summary(console)

        logger.debug(f"*********** Evaluation End: {self.eval_id} ***********")
        return self.result

    def _save_results(self):
        """Save the PerfResult to a JSON file if a path is provided."""
        if self.save_result_to_file and self.result:
            try:
                import json

                fn_path = Path(self.save_result_to_file.format(name=self.name, eval_id=self.eval_id))
                if not fn_path.parent.exists():
                    fn_path.parent.mkdir(parents=True, exist_ok=True)
                fn_path.write_text(json.dumps(asdict(self.result), indent=4))
            except Exception as e:
                logger.warning(f"Failed to save result to file: {e}")
