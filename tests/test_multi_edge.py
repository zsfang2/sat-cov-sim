import math

import pytest

from satellite_coverage.engine.multi_edge import ResourceLimit, solve_edges


def formula(v):
    return 0 if v <= -.78 else 6.9+20*math.log10(math.sqrt((v-.1)**2+1)+v-.1)


def test_single_edge_and_signed_clearance():
    for v in [-2, -.5, 0, 1, 10]:
        height = v*math.sqrt(299792458/1e9*250)/math.sqrt(2)
        result = solve_edges([(500, height)], length_m=1000, frequency_hz=1e9)
        assert result['raw_loss_db'] == pytest.approx(formula(v), abs=1e-6)


def test_two_equal_edges_tie_and_subpath():
    result = solve_edges([(250, 20), (750, 20)], length_m=1000, frequency_hz=1e9)
    root_v = 20*math.sqrt(2/(299792458/1e9*187.5))
    child_v = (20-20/3)*math.sqrt(2/(299792458/1e9*(500*250/750)))
    assert result['selected_edges'][0]['projection_m'] == 250
    assert result['raw_loss_db'] == pytest.approx(formula(root_v)+formula(child_v), abs=1e-6)


def test_ntia_rounded_external_table():
    result = solve_edges([(1200, 140), (2800, 260), (4400, 200), (5800, 220)],
                         length_m=6600, frequency_hz=1.5e9)
    assert result['raw_loss_db'] == pytest.approx(99.86, abs=.05)
    assert [e['projection_m'] for e in result['selected_edges']] == [5800, 2800, 1200]
    assert result['used_loss_db'] == 60
    assert result['cap_triggered']


def test_duplicate_projection_uses_silhouette_and_empty_is_clear():
    a = solve_edges([(500, 10), (500, 20)], length_m=1000, frequency_hz=1e9)
    b = solve_edges([(500, 20)], length_m=1000, frequency_hz=1e9)
    assert a['raw_loss_db'] == b['raw_loss_db']
    assert a['duplicate_projection_count'] == 1
    assert solve_edges([], length_m=1000, frequency_hz=1e9)['raw_loss_db'] == 0


@pytest.mark.parametrize('budget', [dict(maximum_points=1), dict(maximum_nodes=1), dict(maximum_depth=1)])
def test_budget_refusal_never_returns_partial_sum(budget):
    with pytest.raises(ResourceLimit):
        solve_edges([(250, 20), (750, 20)], length_m=1000, frequency_hz=1e9, **budget)


@pytest.mark.parametrize('points', [[(0, 1)], [(1000, 1)], [(500, math.nan)], [(math.inf, 1)]])
def test_invalid_coordinates(points):
    with pytest.raises(ValueError):
        solve_edges(points, length_m=1000, frequency_hz=1e9)


@pytest.mark.parametrize('frequency', [0, -1, math.inf, math.nan, True, 5e-324])
def test_invalid_frequency(frequency):
    with pytest.raises(ValueError):
        solve_edges([(500, 1)], length_m=1000, frequency_hz=frequency)
