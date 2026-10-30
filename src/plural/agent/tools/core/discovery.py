import math
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Final

from pydantic import Field, JsonValue

from plural.agent.providers.base import ToolSchema
from plural.agent.tools.base import PreparedCall, ToolArgs, ToolCtx, ToolResult
from plural.agent.tools.registry import Entry, ToolRegistry
from plural.protocol.models import ToolRisk

TOOL_SEARCH: Final = "tool_search"
DEFAULT_LIMIT: Final = 8
STOP_WORDS: Final = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "with",
    ]
)


def _stem(term: str) -> str:
    if len(term) > 4 and term.endswith("ies"):
        return f"{term[:-3]}y"
    if len(term) > 4 and re.search(r"(ches|shes|sses|xes|zes)$", term):
        return term[:-2]
    if len(term) > 3 and term.endswith("s") and not term.endswith("ss"):
        return term[:-1]
    return term


def tokenize(text: str) -> list[str]:
    """Lowercase terms split at camelCase and non-alphanumerics, without stop words."""
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text).lower()
    return [
        _stem(term) for term in re.split(r"[^a-z0-9]+", spaced) if term and term not in STOP_WORDS
    ]


def _schema_text(schema: JsonValue, parts: list[str]) -> None:
    if not isinstance(schema, dict):
        return
    if isinstance(description := schema.get("description"), str):
        parts.append(description)
    if isinstance(properties := schema.get("properties"), dict):
        for name, value in properties.items():
            parts.append(name)
            _schema_text(value, parts)
    _schema_text(schema.get("items"), parts)


def document(entry: Entry) -> str:
    schema = entry.tool.schema()
    parts = [schema.name, schema.name.replace("_", " "), schema.description, entry.group]
    _schema_text(schema.parameters, parts)
    return " ".join(part for part in parts if part)


def rank(query: str, documents: Sequence[tuple[str, str]], limit: int) -> list[str]:
    """Okapi BM25 over (name, text) pairs. A query that names a tool puts it first."""
    terms = list(dict.fromkeys(tokenize(query)))
    if not terms or not documents:
        return []
    counts = [Counter(tokenize(text)) for _, text in documents]
    lengths = [sum(count.values()) for count in counts]
    average = sum(lengths) / len(documents) or 1
    idf = {
        term: math.log(
            1 + (len(documents) - (seen := sum(term in c for c in counts)) + 0.5) / (seen + 0.5)
        )
        for term in terms
    }
    named = re.sub(r"[^a-z0-9_]", "_", query.strip().lower())
    scored: list[tuple[bool, float, int, str]] = []
    for index, ((name, _), count) in enumerate(zip(documents, counts, strict=True)):
        norm = 1.2 * (1 - 0.75 + 0.75 * lengths[index] / average)
        score = sum(idf[t] * count[t] * 2.2 / (count[t] + norm) for t in terms if count[t])
        if score > 0:
            exact = name == named or name.endswith(f"__{named}")
            scored.append((exact, score, -index, name))
    scored.sort(reverse=True)
    return [name for *_, name in scored[:limit]]


def _summary(entry: Entry) -> str:
    return (entry.tool.schema().description.strip().splitlines() or ["(no description)"])[0]


class ToolSearchArgs(ToolArgs):
    query: str = Field(min_length=1, max_length=200, description="What the tool should do.")
    limit: int = Field(default=DEFAULT_LIMIT, ge=1, le=20)


class ToolSearchTool:
    """Finds deferred tools by keyword and declares the matches from the next model call."""

    name = TOOL_SEARCH

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry

    def schema(self) -> ToolSchema:
        groups = Counter(entry.group for entry in self._registry.deferred())
        listing = ", ".join(f"{group} ({count})" for group, count in sorted(groups.items()))
        return ToolSchema(
            name=self.name,
            description=(
                "Find tools that are not loaded yet and load the matches for your next step. "
                "Search with words for what you need to do, or with a tool's exact name. "
                + (f"Not loaded yet, by group: {listing}." if listing else "Every tool is loaded.")
            ),
            parameters=ToolSearchArgs.model_json_schema(),
        )

    def prepare(self, raw: Mapping[str, JsonValue]) -> PreparedCall:
        args = ToolSearchArgs.model_validate(raw)
        return PreparedCall(
            name=self.name,
            risk=ToolRisk.READ,
            subject=args.query,
            execute=lambda ctx: self._run(args, ctx),
        )

    async def _run(self, args: ToolSearchArgs, ctx: ToolCtx) -> ToolResult:
        candidates = {entry.tool.name: entry for entry in self._registry.deferred()}
        found = rank(
            args.query, [(name, document(e)) for name, e in candidates.items()], args.limit
        )
        if not found:
            return ToolResult(f"No tool that is not loaded yet matches {args.query!r}.")
        self._registry.load(found)
        lines = [f"- {name}: {_summary(candidates[name])}" for name in found]
        return ToolResult("Loaded for your next step:\n" + "\n".join(lines))
