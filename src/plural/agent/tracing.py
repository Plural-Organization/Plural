"""What a run did, as a tree of spans: its model calls, tool calls, waits and sub-agents.

A span is opened where the work starts and closed where it ends, and names its parent, so the
spans of a run form a tree. The tracer only keeps them; the host takes the changed ones as the
run goes, stores them and shows them. A sub-agent's loop shares its parent's tracer and opens
its spans under the tool call that started it, which is how its work shows inside the run.
"""

import time
from collections.abc import Callable
from itertools import count

from plural.protocol.models import Span as SpanView
from plural.protocol.models import SpanKind, SpanStatus, Usage


class Span:
    """An open or finished piece of a run's work. `set` and `end` mark it changed."""

    def __init__(self, tracer: "Tracer", view: SpanView) -> None:
        self._tracer = tracer
        self._view = view
        self._began = time.monotonic()

    @property
    def id(self) -> str:
        return self._view.id

    @property
    def tracer(self) -> "Tracer":
        return self._tracer

    @property
    def view(self) -> SpanView:
        return self._view

    def child(self, kind: SpanKind, name: str, **fields: object) -> "Span":
        return self._tracer.start(kind, name, parent=self, **fields)

    def set(self, **fields: object) -> None:
        self._view = self._view.model_copy(update=fields)
        self._tracer.changed(self)

    def add(self, usage: Usage) -> None:
        self.set(usage=self._view.usage + usage)

    def end(self, status: SpanStatus = SpanStatus.OK, **fields: object) -> None:
        """Close the span. A span closed twice keeps its first ending."""
        if self._view.ended_ms is not None:
            return
        elapsed = round((time.monotonic() - self._began) * 1000)
        self.set(ended_ms=self._view.started_ms + elapsed, status=status, **fields)
        self._tracer.closed(self)

    def moment(
        self, kind: SpanKind, name: str, *, started: float, ended: float, **fields: object
    ) -> None:
        """A finished child that was timed on the monotonic clock while it happened."""
        offset = self._view.started_ms - round(self._began * 1000)
        child = self.child(kind, name, started_ms=round(started * 1000) + offset, **fields)
        child.set(ended_ms=round(ended * 1000) + offset, status=SpanStatus.OK)
        self._tracer.closed(child)


class Tracer:
    def __init__(self, new_id: Callable[[], str] | None = None) -> None:
        numbers = count(1)
        self._new_id = new_id or (lambda: f"sp_{next(numbers)}")
        self._changed: dict[str, Span] = {}
        self._open: dict[str, Span] = {}

    def start(
        self, kind: SpanKind, name: str, *, parent: Span | None = None, **fields: object
    ) -> Span:
        view = SpanView.model_validate(
            {
                "id": self._new_id(),
                "parent_id": parent.id if parent is not None else None,
                "kind": kind,
                "name": name,
                "started_ms": round(time.time() * 1000),
                **fields,
            }
        )
        span = Span(self, view)
        self._changed[span.id] = span
        if view.ended_ms is None:
            self._open[span.id] = span
        return span

    def changed(self, span: Span) -> None:
        self._changed[span.id] = span

    def closed(self, span: Span) -> None:
        self._open.pop(span.id, None)

    def settle(self) -> None:
        """Close what a run left open when it was stopped part-way."""
        for span in list(self._open.values()):
            span.end(SpanStatus.CANCELLED)

    def take(self) -> tuple[SpanView, ...]:
        """The spans opened or changed since the last take, oldest first."""
        spans = tuple(span.view for span in self._changed.values())
        self._changed = {}
        return spans
