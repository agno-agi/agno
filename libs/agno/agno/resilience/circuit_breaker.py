"""Circuit breaker for tool-level failure isolation.

Tracks per-tool failure counts and manages open/half-open/closed state
transitions to prevent repeated calls to broken tools.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel


class CircuitState(str, Enum):
    """State of a circuit breaker."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class _ToolCircuit:
    """Internal state for a single tool's circuit."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    success_count_in_half_open: int = 0


class CircuitBreaker(BaseModel):
    """Configuration for circuit breaker behavior.

    Attributes:
        failure_threshold: Number of consecutive failures before opening the circuit.
        recovery_timeout: Seconds to wait before transitioning from OPEN to HALF_OPEN.
        half_open_max_calls: Number of successful calls in HALF_OPEN state before closing.
    """

    failure_threshold: int = 5
    recovery_timeout: float = 60.0
    half_open_max_calls: int = 1


class CircuitBreakerState:
    """Thread-safe state manager for circuit breakers across multiple tools.

    Usage:
        state = CircuitBreakerState(config=CircuitBreaker(failure_threshold=3))

        # Before calling a tool:
        if state.is_open("my_tool"):
            # skip or use fallback

        # After a successful call:
        state.record_success("my_tool")

        # After a failed call:
        state.record_failure("my_tool")
    """

    def __init__(self, config: CircuitBreaker) -> None:
        self._config = config
        self._circuits: Dict[str, _ToolCircuit] = {}
        self._lock = threading.Lock()

    @property
    def config(self) -> CircuitBreaker:
        return self._config

    def _get_circuit(self, tool_name: str) -> _ToolCircuit:
        """Get or create the circuit for a tool. Must be called under lock."""
        if tool_name not in self._circuits:
            self._circuits[tool_name] = _ToolCircuit()
        return self._circuits[tool_name]

    def get_state(self, tool_name: str) -> CircuitState:
        """Get the current state of a tool's circuit.

        Args:
            tool_name: Name of the tool to check.

        Returns:
            Current CircuitState for the tool.
        """
        with self._lock:
            circuit = self._get_circuit(tool_name)
            self._maybe_transition_to_half_open(circuit)
            return circuit.state

    def is_open(self, tool_name: str) -> bool:
        """Check if a tool's circuit is open (should not be called).

        Args:
            tool_name: Name of the tool to check.

        Returns:
            True if the circuit is OPEN and the tool should be skipped.
        """
        return self.get_state(tool_name) == CircuitState.OPEN

    def record_success(self, tool_name: str) -> None:
        """Record a successful tool call.

        In HALF_OPEN state, increments the success counter and transitions
        to CLOSED if the threshold is met. In CLOSED state, resets the
        failure counter.

        Args:
            tool_name: Name of the tool that succeeded.
        """
        with self._lock:
            circuit = self._get_circuit(tool_name)
            if circuit.state == CircuitState.HALF_OPEN:
                circuit.success_count_in_half_open += 1
                if circuit.success_count_in_half_open >= self._config.half_open_max_calls:
                    circuit.state = CircuitState.CLOSED
                    circuit.failure_count = 0
                    circuit.success_count_in_half_open = 0
            elif circuit.state == CircuitState.CLOSED:
                circuit.failure_count = 0

    def record_failure(self, tool_name: str) -> None:
        """Record a failed tool call.

        Increments the failure counter and opens the circuit if the
        failure threshold is reached. In HALF_OPEN state, immediately
        reopens the circuit.

        Args:
            tool_name: Name of the tool that failed.
        """
        with self._lock:
            circuit = self._get_circuit(tool_name)
            circuit.last_failure_time = time.monotonic()

            if circuit.state == CircuitState.HALF_OPEN:
                # Failure in half-open immediately reopens
                circuit.state = CircuitState.OPEN
                circuit.success_count_in_half_open = 0
            else:
                circuit.failure_count += 1
                if circuit.failure_count >= self._config.failure_threshold:
                    circuit.state = CircuitState.OPEN

    def reset(self, tool_name: Optional[str] = None) -> None:
        """Reset circuit state. If tool_name is None, resets all circuits.

        Args:
            tool_name: Name of the tool to reset, or None to reset all.
        """
        with self._lock:
            if tool_name is None:
                self._circuits.clear()
            elif tool_name in self._circuits:
                self._circuits[tool_name] = _ToolCircuit()

    def _maybe_transition_to_half_open(self, circuit: _ToolCircuit) -> None:
        """Transition from OPEN to HALF_OPEN if the recovery timeout has passed.
        Must be called under lock.
        """
        if circuit.state == CircuitState.OPEN:
            elapsed = time.monotonic() - circuit.last_failure_time
            if elapsed >= self._config.recovery_timeout:
                circuit.state = CircuitState.HALF_OPEN
                circuit.success_count_in_half_open = 0
