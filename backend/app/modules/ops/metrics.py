"""A small in-process metrics registry that renders the Prometheus text exposition format (version 0.0.4).

Counters and histograms are updated on the request path (HTTP metrics); gauges describing the platform (outbox
backlog, pending transactions, worker jobs...) are computed when ``/metrics`` is scraped (see ``collectors``).
The API runs one process per container, so no multi-process aggregation is needed.
"""

from __future__ import annotations

import math
import threading
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

LabelValues = tuple[str, ...]

# Request latency buckets in seconds, from fast cached reads to slow RPC-backed chain actions.
LATENCY_BUCKETS: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(names: Sequence[str], values: Sequence[str], extra: dict[str, str] | None = None) -> str:
    pairs = [f'{n}="{_escape(v)}"' for n, v in zip(names, values, strict=True)]
    pairs += [f'{k}="{_escape(v)}"' for k, v in (extra or {}).items()]
    return "{" + ",".join(pairs) + "}" if pairs else ""


def _number(value: float) -> str:
    if math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    if math.isnan(value):
        return "NaN"
    return repr(float(value)) if not float(value).is_integer() else str(int(value))


@dataclass
class Counter:
    name: str
    help: str
    labels: tuple[str, ...] = ()
    _values: dict[LabelValues, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def inc(self, *label_values: str, amount: float = 1.0) -> None:
        with self._lock:
            self._values[label_values] = self._values.get(label_values, 0.0) + amount

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} counter"
        with self._lock:
            items = sorted(self._values.items())
        for values, value in items:
            yield f"{self.name}{_labels(self.labels, values)} {_number(value)}"


@dataclass
class Histogram:
    name: str
    help: str
    labels: tuple[str, ...] = ()
    buckets: tuple[float, ...] = LATENCY_BUCKETS
    _counts: dict[LabelValues, list[int]] = field(default_factory=dict)
    _sums: dict[LabelValues, float] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe(self, value: float, *label_values: str) -> None:
        with self._lock:
            counts = self._counts.setdefault(label_values, [0] * (len(self.buckets) + 1))
            for i, bound in enumerate(self.buckets):
                if value <= bound:
                    counts[i] += 1
            counts[-1] += 1  # +Inf
            self._sums[label_values] = self._sums.get(label_values, 0.0) + value

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} histogram"
        with self._lock:
            items = sorted((k, list(v), self._sums[k]) for k, v in self._counts.items())
        for values, counts, total in items:
            for bound, count in zip((*self.buckets, math.inf), counts, strict=True):
                le = {"le": _number(bound)}
                yield f"{self.name}_bucket{_labels(self.labels, values, le)} {count}"
            yield f"{self.name}_sum{_labels(self.labels, values)} {_number(total)}"
            yield f"{self.name}_count{_labels(self.labels, values)} {counts[-1]}"


@dataclass
class GaugeFamily:
    """Gauge samples computed for one scrape."""

    name: str
    help: str
    labels: tuple[str, ...] = ()
    samples: list[tuple[LabelValues, float]] = field(default_factory=list)

    def set(self, value: float, *label_values: str) -> GaugeFamily:
        self.samples.append((label_values, value))
        return self

    def render(self) -> Iterable[str]:
        yield f"# HELP {self.name} {self.help}"
        yield f"# TYPE {self.name} gauge"
        for values, value in self.samples:
            yield f"{self.name}{_labels(self.labels, values)} {_number(value)}"


HTTP_REQUESTS = Counter(
    "bountyflow_http_requests_total",
    "HTTP requests handled by the API, by method, route template and status code.",
    ("method", "route", "status"),
)
HTTP_LATENCY = Histogram(
    "bountyflow_http_request_duration_seconds",
    "HTTP request latency in seconds, by method and route template.",
    ("method", "route"),
)
HTTP_EXCEPTIONS = Counter(
    "bountyflow_http_unhandled_exceptions_total",
    "Requests that raised an unhandled exception (answered 500), by route template.",
    ("route",),
)

REQUEST_METRICS: tuple[Counter | Histogram, ...] = (HTTP_REQUESTS, HTTP_LATENCY, HTTP_EXCEPTIONS)


def render(families: Iterable[Counter | Histogram | GaugeFamily]) -> str:
    lines: list[str] = []
    for family in families:
        lines.extend(family.render())
    return "\n".join(lines) + "\n"
