# Builds network graphs by linking entities that show up in the same trial

# Two shapes come out of one code path:
# Bipartite: source and target are different dimensions, like sponsors to drugs.
# Co-occurrence: source and target are the same dimension, like drugs studied together.

# Graphs over thousands of trials can be messy, so weak edges and low-degree
# nodes get dropped. Both cuts are reported so the response can say what was left out.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import combinations

from app.analysis.aggregate import Contribution
from app.analysis.dimensions import UNKNOWN_KEY, Dimension
from app.ctgov.normalize import TrialRecord

# Stops one trial from blowing up the graph. A trial listing 200 countries would add
# about 20,000 pairs on its own, so records over this limit are skipped and counted.
_MAX_VALUES_PER_RECORD = 40


@dataclass
class Node:
    # One entity in the graph, like a sponsor or a drug

    id: str
    label: str
    group: str
    # Which dimension it came from, used to colour the two sides of a bipartite graph

    trial_count: int
    degree: int = 0
    contributions: list[Contribution] = field(default_factory=list)
    # Trials mentioning this entity, so a node can cite its sources like an edge does


@dataclass
class Edge:
    # A link between two entities, weighted by how many trials contain both

    source: str
    target: str
    weight: int
    contributions: list[Contribution] = field(default_factory=list)


@dataclass
class NetworkResult:
    # The finished graph, incluing what got left out

    nodes: list[Node]
    edges: list[Edge]
    source_dimension: Dimension
    target_dimension: Dimension
    is_bipartite: bool
    total_records: int = 0
    nodes_omitted: int = 0
    edges_omitted: int = 0
    records_skipped_for_fanout: int = 0

    @property
    def counting_semantics(self) -> str:
        # What one edge means, shown in the response
        if self.is_bipartite:
            return (
                f"An edge links a {self.source_dimension.label.lower()} to a "
                f"{self.target_dimension.label.lower()} that appear in the same trial; its "
                "weight is the number of such trials."
            )
        return (
            f"An edge links two {self.source_dimension.label.lower()} values that appear "
            "together in the same trial; its weight is the number of trials studying both."
        )


def _entity_values(
    record: TrialRecord, dimension: Dimension
) -> list[tuple[str, str, str]]:
    # Pull out (key, label, excerpt) for each value, skipping the unknown bucket.
    # A trial that doesn't report the field adds no node, because an "Unknown" node
    # would link unrelated trials together into one meaningless hub.
    return [
        (v.key, v.label, v.source_excerpt)
        for v in dimension.extract(record)
        if v.key != UNKNOWN_KEY
    ]


def build_network(
    records: Sequence[TrialRecord],
    *,
    source_dimension: Dimension,
    target_dimension: Dimension,
    min_edge_weight: int = 2,
    max_nodes: int = 60,
    top_k_per_side: int | None = None,
) -> NetworkResult:
    # Build the graph, then condense it to something readable
    is_bipartite = source_dimension.id != target_dimension.id

    # Pass 1: how often each entity appears, so it can be restricted to the busiest before
    # doing the quadratic work of pairing them.
    source_counts: dict[str, int] = {}
    target_counts: dict[str, int] = {}
    labels: dict[str, str] = {}
    entity_contributions: dict[str, list[Contribution]] = {}

    for record in records:
        for key, label, excerpt in _entity_values(record, source_dimension):
            source_counts[key] = source_counts.get(key, 0) + 1
            labels.setdefault(key, label)
            entity_contributions.setdefault(key, []).append(
                Contribution(record=record, excerpt=excerpt)
            )
        if is_bipartite:
            for key, label, excerpt in _entity_values(record, target_dimension):
                target_counts[key] = target_counts.get(key, 0) + 1
                labels.setdefault(key, label)
                entity_contributions.setdefault(key, []).append(
                    Contribution(record=record, excerpt=excerpt)
                )

    if not is_bipartite:
        target_counts = source_counts

    allowed_source = set(source_counts)
    allowed_target = set(target_counts)
    if top_k_per_side is not None:
        allowed_source = set(
            sorted(source_counts, key=lambda k: -source_counts[k])[:top_k_per_side]
        )
        allowed_target = (
            allowed_source
            if not is_bipartite
            else set(sorted(target_counts, key=lambda k: -target_counts[k])[:top_k_per_side])
        )

    # Pass 2: accumulate the edges.
    edges: dict[tuple[str, str], Edge] = {}
    skipped_for_fanout = 0

    for record in records:
        sources = [t for t in _entity_values(record, source_dimension) if t[0] in allowed_source]
        if is_bipartite:
            targets = [
                t for t in _entity_values(record, target_dimension) if t[0] in allowed_target
            ]
        else:
            targets = sources

        if len(sources) > _MAX_VALUES_PER_RECORD or len(targets) > _MAX_VALUES_PER_RECORD:
            skipped_for_fanout += 1
            continue

        if is_bipartite:
            pairs = [
                ((s_key, t_key), f"{s_excerpt} → {t_excerpt}")
                for s_key, _, s_excerpt in sources
                for t_key, _, t_excerpt in targets
            ]
        else:
            # Unordered pairs; sorting the key makes (a,b) and (b,a) the same edge.
            pairs = [
                (tuple(sorted((a[0], b[0]))), f"{a[2]} + {b[2]}")
                for a, b in combinations(sources, 2)
                if a[0] != b[0]
            ]

        for pair, excerpt in pairs:
            edge = edges.get(pair)  # type: ignore[arg-type]
            if edge is None:
                edge = Edge(source=pair[0], target=pair[1], weight=0)
                edges[pair] = edge  # type: ignore[index]
            edge.weight += 1
            edge.contributions.append(Contribution(record=record, excerpt=excerpt))

    total_edges = len(edges)
    surviving = [e for e in edges.values() if e.weight >= min_edge_weight]

    # Rank nodes by degree within the surviving edges, then keep the busiest.
    degree: dict[str, int] = {}
    for edge in surviving:
        degree[edge.source] = degree.get(edge.source, 0) + edge.weight
        degree[edge.target] = degree.get(edge.target, 0) + edge.weight

    total_nodes = len(degree)
    kept_ids = set(sorted(degree, key=lambda k: -degree[k])[:max_nodes])
    surviving = [e for e in surviving if e.source in kept_ids and e.target in kept_ids]

    # Degrees are recomputed after node condenses, so the figure describes the graph as
    # rendered, not the graph before trimming.
    final_degree: dict[str, int] = {}
    for edge in surviving:
        final_degree[edge.source] = final_degree.get(edge.source, 0) + 1
        final_degree[edge.target] = final_degree.get(edge.target, 0) + 1

    def _group_of(key: str) -> str:
        # Which side of the graph a node sits on, which decides its colour.
        # In a co-occurrence graph, both dimensions are the same, so every node shares
        # one group. If a value somehow appears on both sides, the source wins.
        return source_dimension.id if key in source_counts else target_dimension.id

    nodes = [
        Node(
            id=key,
            label=labels.get(key, key),
            group=_group_of(key),
            trial_count=source_counts.get(key, target_counts.get(key, 0)),
            degree=final_degree.get(key, 0),
            contributions=entity_contributions.get(key, []),
        )
        for key in kept_ids
        if key in final_degree
    ]
    nodes.sort(key=lambda n: (-n.degree, n.label.lower()))
    node_ids = {n.id for n in nodes}
    surviving = [e for e in surviving if e.source in node_ids and e.target in node_ids]
    surviving.sort(key=lambda e: (-e.weight, e.source, e.target))

    return NetworkResult(
        nodes=nodes,
        edges=surviving,
        source_dimension=source_dimension,
        target_dimension=target_dimension,
        is_bipartite=is_bipartite,
        total_records=len(records),
        nodes_omitted=max(total_nodes - len(nodes), 0),
        edges_omitted=max(total_edges - len(surviving), 0),
        records_skipped_for_fanout=skipped_for_fanout,
    )
