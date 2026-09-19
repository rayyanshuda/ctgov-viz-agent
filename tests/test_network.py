"""Graph construction: bipartite links, co-occurrence, pruning and citations."""

from __future__ import annotations

from app.analysis.dimensions import UNKNOWN_KEY, get_dimension
from app.analysis.network import build_network


def net(records, source="lead_sponsor", target="intervention_mesh", **kwargs):
    return build_network(
        records,
        source_dimension=get_dimension(source),
        target_dimension=get_dimension(target),
        **kwargs,
    )


class TestBipartite:
    def test_nodes_are_labelled_by_their_side(self, records):
        result = net(records, min_edge_weight=1, max_nodes=100)
        assert result.is_bipartite
        groups = {n.group for n in result.nodes}
        assert groups <= {"lead_sponsor", "intervention_mesh"}

    def test_edges_only_join_the_two_sides(self, records):
        result = net(records, min_edge_weight=1, max_nodes=100)
        by_id = {n.id: n.group for n in result.nodes}
        for edge in result.edges:
            assert by_id[edge.source] != by_id[edge.target]

    def test_semantics_describe_the_edge_meaning(self, records):
        assert "appear in the same trial" in net(records, min_edge_weight=1).counting_semantics


class TestCoOccurrence:
    def test_same_dimension_gives_one_group(self, records):
        result = net(records, source="intervention_mesh", target="intervention_mesh",
                     min_edge_weight=1, max_nodes=100)
        assert not result.is_bipartite
        assert {n.group for n in result.nodes} == {"intervention_mesh"}

    def test_pairs_are_unordered_so_a_b_and_b_a_are_one_edge(self, synthetic_records):
        result = net(synthetic_records, source="intervention_mesh",
                     target="intervention_mesh", min_edge_weight=1)
        pairs = {frozenset((e.source, e.target)) for e in result.edges}
        assert len(pairs) == len(result.edges)

    def test_no_self_loops(self, records):
        result = net(records, source="intervention_mesh", target="intervention_mesh",
                     min_edge_weight=1, max_nodes=100)
        assert all(e.source != e.target for e in result.edges)

    def test_edge_weight_counts_trials_studying_both(self, synthetic_records):
        # NCT...01 lists aspirin + warfarin; nothing else pairs them.
        result = net(synthetic_records, source="intervention_mesh",
                     target="intervention_mesh", min_edge_weight=1)
        weights = {frozenset((e.source, e.target)): e.weight for e in result.edges}
        assert weights[frozenset(("aspirin", "warfarin"))] == 1


class TestPruning:
    def test_min_edge_weight_removes_weak_links(self, records):
        loose = net(records, min_edge_weight=1, max_nodes=300)
        tight = net(records, min_edge_weight=3, max_nodes=300)
        assert len(tight.edges) < len(loose.edges)
        assert all(e.weight >= 3 for e in tight.edges)
        assert tight.edges_omitted > 0

    def test_max_nodes_caps_the_graph(self, records):
        result = net(records, min_edge_weight=1, max_nodes=10)
        assert len(result.nodes) <= 10

    def test_edges_never_reference_a_pruned_node(self, records):
        result = net(records, min_edge_weight=1, max_nodes=8)
        ids = {n.id for n in result.nodes}
        assert all(e.source in ids and e.target in ids for e in result.edges)

    def test_degree_reflects_the_rendered_graph(self, records):
        result = net(records, min_edge_weight=2, max_nodes=15)
        expected = {n.id: 0 for n in result.nodes}
        for edge in result.edges:
            expected[edge.source] += 1
            expected[edge.target] += 1
        assert {n.id: n.degree for n in result.nodes} == expected

    def test_isolated_nodes_are_not_returned(self, records):
        result = net(records, min_edge_weight=5, max_nodes=100)
        assert all(n.degree > 0 for n in result.nodes)

    def test_top_k_per_side_restricts_before_pairing(self, records):
        result = net(records, min_edge_weight=1, max_nodes=200, top_k_per_side=5)
        by_group: dict[str, int] = {}
        for node in result.nodes:
            by_group[node.group] = by_group.get(node.group, 0) + 1
        assert all(count <= 5 for count in by_group.values())


class TestUnknownHandling:
    def test_unreported_values_do_not_become_a_hub_node(self, synthetic_records):
        # NCT...03 reports no sponsor and no drugs. An "Unknown" node would falsely link
        # every incomplete trial to every other.
        result = net(synthetic_records, min_edge_weight=1)
        assert UNKNOWN_KEY not in {n.id for n in result.nodes}


class TestCitations:
    def test_edges_carry_the_trials_that_justify_them(self, records):
        result = net(records, min_edge_weight=2, max_nodes=20)
        for edge in result.edges:
            assert len(edge.contributions) == edge.weight
            assert all(c.record.nct_id.startswith("NCT") for c in edge.contributions)

    def test_nodes_carry_their_own_supporting_trials(self, records):
        result = net(records, min_edge_weight=2, max_nodes=20)
        assert all(n.contributions for n in result.nodes)
