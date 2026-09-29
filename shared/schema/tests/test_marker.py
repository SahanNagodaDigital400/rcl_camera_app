"""`shared_schema.marker` — the Marker's rules and the size match they feed.

The rules, not the library: `api.measure` does the geometry and
`apps/api/tests/test_marker_dictionaries.py` pins the fiducial id ranges
against the OpenCV that is installed. This file is about what the contract
itself promises, and it is the half `apps/web`'s TypeScript twin mirrors.

The cases below are the real catalogue's, not invented ones: the four Sizes in
the source tree, and the `45X90`-against-`60X30` pair that is the whole reason
a measurement is worth taking.
"""

from __future__ import annotations

import pytest
from shared_schema.marker import (
    ARUCO_DICTIONARY_SIZES,
    MAX_MARKER_EDGE_MM,
    MAX_MARKER_NAME_LENGTH,
    MIN_MARKER_EDGE_MM,
    SIZE_MATCH_TOLERANCE,
    ArucoDictionary,
    clean_edge_mm,
    clean_marker_name,
    match_size,
    size_dimensions_mm,
    validate_aruco_pair,
)

#: The Sizes the real source tree holds, as `tile_size` normalizes them.
CATALOGUE = ["30X90", "40X40", "45X90", "60X30"]


class TestCleanMarkerName:
    def test_trims_and_collapses(self) -> None:
        assert clean_marker_name("  Rocell   ID  badge ") == "Rocell ID badge"

    def test_case_is_preserved(self) -> None:
        """**Not uppercased**, unlike a Size, and the difference is the purpose.

        A Size is an identifier the catalogue joins on. This is a label a human
        reads off a picker, and shouting it would make the one screen it
        appears on harder to scan rather than easier.
        """
        assert clean_marker_name("Rocell ID badge") == "Rocell ID badge"

    @pytest.mark.parametrize("blank", ["", "   ", "\t\n "])
    def test_blank_is_refused(self, blank: str) -> None:
        with pytest.raises(ValueError, match="must not be blank"):
            clean_marker_name(blank)

    def test_control_characters_are_refused(self) -> None:
        """A NUL cannot cross psycopg at all — it would surface as a 500."""
        with pytest.raises(ValueError, match="control characters"):
            clean_marker_name("badge\x00")

    def test_the_length_bound_is_the_declared_one(self) -> None:
        assert clean_marker_name("a" * MAX_MARKER_NAME_LENGTH)
        with pytest.raises(ValueError, match="at most"):
            clean_marker_name("a" * (MAX_MARKER_NAME_LENGTH + 1))


class TestCleanEdgeMm:
    def test_accepts_a_bank_card(self) -> None:
        """ISO/IEC 7810 ID-1 — the marker most staff already carry."""
        assert clean_edge_mm(85.60, "width") == pytest.approx(85.60)
        assert clean_edge_mm(53.98, "height") == pytest.approx(53.98)

    @pytest.mark.parametrize("edge", ["width", "height"])
    def test_the_message_names_the_field_that_failed(self, edge: str) -> None:
        """A form with two dimension fields must say which one was wrong."""
        with pytest.raises(ValueError, match=edge):
            clean_edge_mm(1.0, edge)

    def test_bounds_are_the_declared_ones(self) -> None:
        assert clean_edge_mm(MIN_MARKER_EDGE_MM, "width") == MIN_MARKER_EDGE_MM
        assert clean_edge_mm(MAX_MARKER_EDGE_MM, "width") == MAX_MARKER_EDGE_MM
        with pytest.raises(ValueError):
            clean_edge_mm(MIN_MARKER_EDGE_MM - 0.1, "width")
        with pytest.raises(ValueError):
            clean_edge_mm(MAX_MARKER_EDGE_MM + 0.1, "width")

    @pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
    def test_nan_and_infinity_are_refused(self, value: float) -> None:
        """A `NaN` width renders as "NaNmm" and scales every measurement to `NaN`.

        It fails nowhere a reader can see, which is exactly why it is refused
        at the contract rather than left to the geometry.
        """
        with pytest.raises(ValueError):
            clean_edge_mm(value, "width")


class TestValidateArucoPair:
    def test_neither_is_a_plain_object(self) -> None:
        """A bank card with nothing printed on it is a perfectly good ruler."""
        assert validate_aruco_pair(None, None) == (None, None)

    def test_both_is_a_detectable_card(self) -> None:
        assert validate_aruco_pair(ArucoDictionary.DICT_4X4_50, 7) == (
            ArucoDictionary.DICT_4X4_50,
            7,
        )

    @pytest.mark.parametrize(
        ("dictionary", "aruco_id"),
        [(ArucoDictionary.DICT_4X4_50, None), (None, 7)],
    )
    def test_half_a_declaration_is_refused(
        self, dictionary: ArucoDictionary | None, aruco_id: int | None
    ) -> None:
        """Half a fiducial is a card the detector will never find.

        Nobody would be told why: detection simply returns nothing, which is
        indistinguishable from a creased card or bad light.
        """
        with pytest.raises(ValueError, match="both"):
            validate_aruco_pair(dictionary, aruco_id)

    @pytest.mark.parametrize("dictionary", list(ArucoDictionary))
    def test_the_id_is_bounded_by_its_own_family(self, dictionary: ArucoDictionary) -> None:
        limit = ARUCO_DICTIONARY_SIZES[dictionary]
        assert validate_aruco_pair(dictionary, limit - 1) == (dictionary, limit - 1)
        with pytest.raises(ValueError, match="holds ids"):
            validate_aruco_pair(dictionary, limit)
        with pytest.raises(ValueError, match="holds ids"):
            validate_aruco_pair(dictionary, -1)


class TestSizeDimensionsMm:
    @pytest.mark.parametrize(
        ("size", "expected"),
        [
            ("45X90", (450.0, 900.0)),
            ("60X30", (300.0, 600.0)),
            ("40X40", (400.0, 400.0)),
            ("30X90", (300.0, 900.0)),
        ],
    )
    def test_reads_the_real_catalogue(self, size: str, expected: tuple[float, float]) -> None:
        """Folder names are centimetres; the measurement is millimetres."""
        assert size_dimensions_mm(size) == expected

    def test_always_short_edge_first(self) -> None:
        """So a comparison never has to know which way round it was written."""
        assert size_dimensions_mm("60X30") == size_dimensions_mm("30X60")

    @pytest.mark.parametrize("unreadable", ["POLISH", "", "45x90cm", "45", "0X90", "45-90"])
    def test_none_rather_than_a_guess(self, unreadable: str) -> None:
        """`tile.face_number`'s rule: nothing guarantees a future Size spells
        its dimensions the way the four in the real tree do, and a Size this
        cannot read simply never matches — the millimetres are still reported.
        """
        assert size_dimensions_mm(unreadable) is None


class TestMatchSize:
    def test_separates_the_pair_that_matters(self) -> None:
        """`45X90` against `60X30` — both 2:1, so only millimetres separate them.

        This is the entire justification for the feature, as an assertion.
        """
        assert match_size(300.0, 600.0, CATALOGUE) == "60X30"
        assert match_size(450.0, 900.0, CATALOGUE) == "45X90"

    def test_both_edges_must_agree(self) -> None:
        """Requiring both is what makes the check shape-aware for free.

        A 600x300 measurement cannot match `45X90` however the tolerance is
        set, because 300 is nowhere near 450.
        """
        assert match_size(300.0, 900.0, CATALOGUE) == "30X90"
        assert match_size(400.0, 400.0, CATALOGUE) == "40X40"

    def test_nothing_close_enough_matches_nothing(self) -> None:
        """**Never "the nearest Size anyway".**

        A 300mm-out nearest is a wrong answer wearing a right answer's clothes,
        and under AD-19 a wrong Size makes the true Tile unreachable.
        """
        assert match_size(800.0, 1600.0, CATALOGUE) is None
        assert match_size(50.0, 100.0, CATALOGUE) is None

    def test_the_tolerance_band_is_the_declared_one(self) -> None:
        inside = 600.0 * (1.0 + SIZE_MATCH_TOLERANCE * 0.9)
        outside = 600.0 * (1.0 + SIZE_MATCH_TOLERANCE * 1.1)
        assert match_size(300.0 * (1.0 + SIZE_MATCH_TOLERANCE * 0.9), inside, ["60X30"]) == "60X30"
        assert match_size(300.0, outside, ["60X30"]) is None

    def test_the_tolerance_cannot_confuse_the_hard_pair(self) -> None:
        """The band is narrower than half the gap it has to resolve.

        `45X90` and `60X30` are exactly 1.5x apart. Splitting them at the
        geometric mean tolerates about 18%, so a tolerance at or under that can
        never let one match the other — asserted here rather than argued in a
        comment, so lowering the gap or raising the tolerance fails the build.
        """
        assert SIZE_MATCH_TOLERANCE < 0.18
        assert match_size(300.0, 600.0, ["45X90"]) is None
        assert match_size(450.0, 900.0, ["60X30"]) is None

    def test_an_unreadable_size_is_skipped_not_fatal(self) -> None:
        assert match_size(300.0, 600.0, ["POLISH", "60X30"]) == "60X30"
        assert match_size(300.0, 600.0, ["POLISH"]) is None

    def test_the_closest_wins_among_those_inside_the_band(self) -> None:
        assert match_size(305.0, 610.0, ["60X30", "30X60"]) in {"60X30", "30X60"}
        assert match_size(300.0, 600.0, []) is None
