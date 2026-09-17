"""The skeleton must import, state the AD-1 invariant, and refuse to pretend."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import shared_vision


def test_module_imports_and_exposes_a_pipeline_version() -> None:
    assert isinstance(shared_vision.PIPELINE_VERSION, str)
    assert shared_vision.PIPELINE_VERSION


def test_module_docstring_records_the_ad1_invariant() -> None:
    doc = shared_vision.__doc__ or ""

    assert "AD-1" in doc
    assert "identical" in doc
    assert shared_vision.PORT_SOURCE in doc


def test_port_source_points_at_the_poc_module() -> None:
    assert shared_vision.PORT_SOURCE == "poc/tilematch/vision.py"


@pytest.mark.parametrize("func", [shared_vision.preprocess, shared_vision.embed])
def test_unimplemented_entry_points_raise_rather_than_return(
    func: Callable[[Any], Any],
) -> None:
    with pytest.raises(NotImplementedError) as raised:
        func(object())

    assert "not implemented yet" in str(raised.value)
