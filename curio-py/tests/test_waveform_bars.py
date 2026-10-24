"""Tests for diamond waveform bar height calculator."""

import pytest
from curio.ui.waveform_bars import compute_bar_heights, DIAMOND_WEIGHTS, BAR_COUNT


def test_full_volume():
    result = compute_bar_heights(1.0, max_height=20.0, min_height=2.0)
    assert result == pytest.approx([10.0, 14.0, 18.0, 20.0, 20.0, 18.0, 14.0, 10.0])


def test_silent():
    result = compute_bar_heights(0.0, max_height=20.0, min_height=2.0)
    assert result == pytest.approx([2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0, 2.0])


def test_half_volume():
    result = compute_bar_heights(0.5, max_height=20.0, min_height=2.0)
    assert result == pytest.approx([5.0, 7.0, 9.0, 10.0, 10.0, 9.0, 7.0, 5.0])


def test_always_8_bars():
    result = compute_bar_heights(0.75, max_height=30.0, min_height=1.0)
    assert len(result) == 8


def test_diamond_weights_constant():
    assert DIAMOND_WEIGHTS == (0.5, 0.7, 0.9, 1.0, 1.0, 0.9, 0.7, 0.5)
    assert BAR_COUNT == 8


def test_rms_clamped_above():
    result = compute_bar_heights(1.5, max_height=20.0, min_height=2.0)
    expected = compute_bar_heights(1.0, max_height=20.0, min_height=2.0)
    assert result == pytest.approx(expected)


def test_negative_rms():
    result = compute_bar_heights(-0.1, max_height=20.0, min_height=2.0)
    expected = compute_bar_heights(0.0, max_height=20.0, min_height=2.0)
    assert result == pytest.approx(expected)
