"""`shared_schema.marker.ARUCO_DICTIONARY_SIZES` against the OpenCV that is installed.

`shared_schema` states how many ids each fiducial family holds, and it states
it as plain integers rather than reading them from `cv2`. That is deliberate
and load-bearing: `shared-schema` is the contract `apps/web` compiles against
through its TypeScript twin, and it must not gain a 53MB native dependency to
validate a number. A rule that only holds where OpenCV is installed is not a
contract.

The cost of writing the numbers down is that they can drift from the library
that actually does the detecting — and the drift is silent in the worst
direction. An id the contract accepts but the family does not hold is a Marker
an Administrator can register, print a card for, and never successfully measure
with, with nothing to distinguish that from bad lighting.

This file is where the two meet. It lives in `apps/api` rather than in
`shared/schema/tests` because this is the package that actually depends on
OpenCV; the contract's own suite tests the rules, not the library.
"""

from __future__ import annotations

import cv2
import pytest
from api.measure import _OPENCV_DICTIONARIES
from shared_schema.marker import ARUCO_DICTIONARY_SIZES, ArucoDictionary


@pytest.mark.parametrize("dictionary", list(ArucoDictionary))
def test_every_declared_family_is_mapped_to_opencv(dictionary: ArucoDictionary) -> None:
    """Each family the contract offers can actually be asked for.

    A member added to `ArucoDictionary` without a line in `_OPENCV_DICTIONARIES`
    is a family an Administrator can pick and `detect_marker` raises `KeyError`
    on — a `500` on an ordinary measurement.
    """
    assert dictionary in _OPENCV_DICTIONARIES


@pytest.mark.parametrize("dictionary", list(ArucoDictionary))
def test_the_declared_id_count_is_the_real_one(dictionary: ArucoDictionary) -> None:
    """The contract's id bound is the family's own size, not an approximation.

    `bytesList` carries one row per marker the family defines, so its length is
    the count — and the contract's `validate_aruco_pair` refuses anything at or
    above it.
    """
    family = cv2.aruco.getPredefinedDictionary(_OPENCV_DICTIONARIES[dictionary])
    assert ARUCO_DICTIONARY_SIZES[dictionary] == len(family.bytesList)


@pytest.mark.parametrize("dictionary", list(ArucoDictionary))
def test_the_last_accepted_id_can_be_printed(dictionary: ArucoDictionary) -> None:
    """The top of the accepted range is a card that really exists.

    An off-by-one in the count above would be invisible to the length check if
    both sides were wrong the same way. This asks the library to draw the
    highest id the contract accepts, which only succeeds if that id is real.
    """
    family = cv2.aruco.getPredefinedDictionary(_OPENCV_DICTIONARIES[dictionary])
    highest = ARUCO_DICTIONARY_SIZES[dictionary] - 1
    printed = cv2.aruco.generateImageMarker(family, highest, 120)
    assert printed.shape == (120, 120)


def test_the_contract_covers_every_mapped_family() -> None:
    """Both directions, so neither table can grow a member the other lacks."""
    assert set(ARUCO_DICTIONARY_SIZES) == set(_OPENCV_DICTIONARIES)
    assert set(ARUCO_DICTIONARY_SIZES) == set(ArucoDictionary)
