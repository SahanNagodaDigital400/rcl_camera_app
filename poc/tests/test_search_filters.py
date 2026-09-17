"""Size filtering, the display rules, and catalogue search.

The size filter and the match bar are the only things standing between "the user
declared 45X90" and a 60X30 reference winning the scan, so they are tested
against a synthetic index rather than the real one — the real index takes 20
minutes to build and its contents would make the assertions depend on the
catalogue.
"""

import json

import numpy as np
import pytest
from tilematch import server, vision
from tilematch.search import Matcher, UnknownSize

SIZES = ["45X90", "45X90", "60X30", "60X30", "40X40"]


@pytest.fixture
def index(tmp_path):
    """A four-size index of orthogonal unit vectors, one vector per reference.

    Orthogonal so every similarity is 0 except the one under test: that makes
    "which reference won" an exact assertion rather than a threshold.
    """
    n = len(SIZES)
    vectors = np.eye(n, vision.EMBED_DIM, dtype=np.float32)
    np.savez(tmp_path / "vectors.npz", vectors=vectors, owners=np.arange(n))
    (tmp_path / "meta.json").write_text(json.dumps({
        "config_hash": vision.config_hash(),
        "references": [
            {"relpath": f"{s}/D{i}/x.jpg", "size": s, "design": f"D{i}",
             "code": f"C{i}", "face": None, "product": f"{s} / D{i}",
             "design_unknown": False, "thumb": f"thumbs/{i:04d}.jpg"}
            for i, s in enumerate(SIZES)
        ],
    }))
    return Matcher(tmp_path)


def fake_query(index, hit: int, monkeypatch):
    """Make embed_query return the vector of reference `hit`, exactly."""
    monkeypatch.setattr(
        Matcher, "embed_query", lambda self, img: index.vectors[hit : hit + 1]
    )


def test_sizes_reports_the_catalogue_not_a_hard_coded_list(index):
    got = {e["size"]: e for e in index.sizes()}
    assert set(got) == {"45X90", "60X30", "40X40"}
    assert got["45X90"]["tiles"] == 2
    assert got["45X90"]["categories"] == 2
    # Largest catalogue first, so the picker leads with the likely choice.
    assert [e["size"] for e in index.sizes()][0] in {"45X90", "60X30"}


def test_size_filter_excludes_every_other_size(index, monkeypatch):
    fake_query(index, 2, monkeypatch)                 # a 60X30 reference wins
    assert index.search(None, k=3)[0].ref_id == 2

    out = index.search(None, k=3, size="45X90")
    assert out, "a 45X90 filter must still return the best 45X90 candidates"
    assert {c.size for c in out} == {"45X90"}
    assert 2 not in {c.ref_id for c in out}


def test_size_filter_returns_fewer_than_k_rather_than_padding(index, monkeypatch):
    # 40X40 holds exactly one reference. Asking for three must yield one, not
    # one plus two arbitrary tiles of some other size.
    fake_query(index, 4, monkeypatch)
    out = index.search(None, k=3, size="40X40")
    assert len(out) == 1
    assert out[0].size == "40X40"
    assert [c.rank for c in out] == [1]


def test_unknown_size_is_refused_not_silently_empty(index, monkeypatch):
    fake_query(index, 0, monkeypatch)
    with pytest.raises(UnknownSize):
        index.search(None, k=3, size="99X99")


def test_exclude_still_applies_under_a_size_filter(index, monkeypatch):
    fake_query(index, 0, monkeypatch)
    out = index.search(None, k=3, size="45X90", exclude={0})
    assert [c.ref_id for c in out] == [1]


def test_match_floor_is_a_prefix_of_the_ranked_list(index, monkeypatch):
    # The server counts candidates above the bar and returns the whole list, so
    # "above_floor" is only meaningful if scores are monotonically decreasing.
    fake_query(index, 0, monkeypatch)
    scores = [c.score for c in index.search(None, k=5)]
    assert scores == sorted(scores, reverse=True)


def test_match_floor_is_a_display_bar_not_a_search_parameter():
    # search.TOP_K feeds the eval harness and must stay independent of what the
    # page chooses to paint, or a filtered display would relabel the metric.
    from tilematch.search import TOP_K

    assert TOP_K == 3
    assert 0.0 < server.MATCH_FLOOR < 1.0
    assert server.DISPLAY_K == 3


class TestTileIsTheUnitOfIdentity:
    """Regression guard for the correction that each FILE is a different tile.

    The POC originally treated `size + category` as the unit of identity and the
    files inside a folder as faces of one product. That inflated every accuracy
    number and made leave-one-out look meaningful. If someone reintroduces the
    grouping, these fail.
    """

    def test_candidates_are_never_collapsed_by_category(self, index, monkeypatch):
        # References 0 and 1 share a size but are distinct tiles; both must be
        # offerable, because either could be the one in the user's hand.
        fake_query(index, 0, monkeypatch)
        out = index.search(None, k=5, size="45X90")
        assert [c.ref_id for c in out] == [0, 1]
        assert len({c.ref_id for c in out}) == len(out)

    def test_every_reference_has_its_own_identity(self, index):
        assert len({r["code"] for r in index.references}) == len(index.references)

    def test_category_is_exposed_as_a_grouping_not_a_product(self, index, monkeypatch):
        fake_query(index, 0, monkeypatch)
        d = index.search(None, k=1)[0].as_dict()
        assert "category" in d
        assert "product" not in d, "'product' implies files in a folder share an identity"

    def test_eval_scores_the_exact_tile(self, index, monkeypatch):
        from tilematch.evaluate import _score

        fake_query(index, 0, monkeypatch)
        cands = index.search(None, k=3, size="45X90")
        # Truth is reference 1: same folder as the top hit, different tile.
        s = _score(cands, truth_id=1, truth_folder=index.references[1]["product"])
        assert s["top1"] == 0, "a different tile from the same folder is not a top-1 hit"
        assert s["top3"] == 1, "reference 1 is in the top 3, so top-3 is a hit"
        assert s["same_folder_top3"] == 1, "the loose number stays available as a diagnostic"


class TestScoreIsNotOnScreen:
    """The match percentage is gone from the UI and must stay gone.

    It was a toggle; it is now removed, because a bare percentage beside a tile
    code reads as confidence whatever the caption says, and here it is not
    confidence — a wrong top-1 medians 0.907 against 0.918 for a correct one.
    Removing it from the screen must never remove it from the API or the log,
    which is the difference between a display decision and losing the ability to
    debug a scan.
    """

    def test_score_survives_in_the_payload(self, index, monkeypatch):
        fake_query(index, 0, monkeypatch)
        assert "score" in index.search(None, k=1)[0].as_dict()

    def test_no_score_toggle_remains(self):
        # A leftover SHOW_SCORE would mean a second, contradictory source of
        # truth for something that is now a flat decision.
        assert not hasattr(server, "SHOW_SCORE")

    def test_page_never_renders_a_percentage(self):
        page = (server.WEB_DIR / "index.html").read_text()
        assert "showScore" not in page
        assert "c.score" not in page, "the card must not print the similarity"

    def test_build_stamp_tracks_display_config(self, monkeypatch):
        # A stamp that missed a display knob would report "current" while the
        # page showed something else.
        import importlib

        on = importlib.reload(server).build_stamp()
        monkeypatch.setenv("TILEMATCH_EXPAND", "0.99")
        try:
            assert importlib.reload(server).build_stamp() != on
        finally:
            monkeypatch.delenv("TILEMATCH_EXPAND")
            importlib.reload(server)


class TestDisplayCount:
    """How many candidates the results screen paints.

    Three that clear the match bar, unless more than three clear the expand bar —
    then all of those. The server owns the rule and sends the count, so the page
    cannot disagree with the log about what staff saw.
    """

    @staticmethod
    def cands(*scores):
        from tilematch.search import Candidate

        return [
            Candidate(rank=i, ref_id=i, score=s, code=f"C{i}", size="45X90",
                      design="D", face=None, category="45X90 / D",
                      thumb="t.jpg", relpath="r.jpg", design_unknown=False)
            for i, s in enumerate(scores, 1)
        ]

    def test_three_when_nothing_clears_the_expand_bar(self):
        got = server.display_count(self.cands(0.70, 0.68, 0.60, 0.55, 0.52),
                                   floor=0.50, expand=0.75, k=3)
        assert got == 3

    def test_expand_bar_shows_every_candidate_above_it(self):
        got = server.display_count(self.cands(0.92, 0.88, 0.81, 0.78, 0.76, 0.60),
                                   floor=0.50, expand=0.75, k=3)
        assert got == 5, "all five at or above 0.75 are shown, not just three"

    def test_expand_bar_is_inclusive_of_its_own_value(self):
        got = server.display_count(self.cands(0.90, 0.80, 0.75, 0.75),
                                   floor=0.50, expand=0.75, k=3)
        assert got == 4

    def test_expand_bar_never_shortens_the_list_below_k(self):
        # One candidate above 0.75 must not cut the list from three to one — the
        # expand bar only ever lengthens what the match bar already allowed.
        got = server.display_count(self.cands(0.80, 0.70, 0.65, 0.60),
                                   floor=0.50, expand=0.75, k=3)
        assert got == 3

    def test_match_bar_still_caps_the_list(self):
        got = server.display_count(self.cands(0.60, 0.40, 0.30),
                                   floor=0.50, expand=0.75, k=3)
        assert got == 1

    def test_nothing_above_the_match_bar_shows_nothing(self):
        got = server.display_count(self.cands(0.40, 0.30),
                                   floor=0.50, expand=0.75, k=3)
        assert got == 0, "the empty state exists precisely for this"

    def test_defaults_are_a_sane_pair(self):
        assert 0.0 < server.MATCH_FLOOR <= server.EXPAND_FLOOR < 1.0
        assert server.EXPAND_FLOOR == 0.75

    def test_expand_floor_is_overridable_without_a_code_edit(self, monkeypatch):
        import importlib

        monkeypatch.setenv("TILEMATCH_EXPAND", "0.9")
        try:
            assert importlib.reload(server).EXPAND_FLOOR == 0.9
        finally:
            monkeypatch.delenv("TILEMATCH_EXPAND")
            importlib.reload(server)


class TestLookup:
    """Text search over the catalogue.

    Secondary to the camera and deliberately dumb: substring matching over the
    file name, size and category, with no vector anywhere near it.
    """

    def test_finds_a_tile_by_its_exact_code(self, index):
        assert [h["code"] for h in index.lookup("C3")] == ["C3"]

    def test_is_case_insensitive(self, index):
        assert index.lookup("c3") == index.lookup("C3")

    def test_matches_on_size(self, index):
        assert {h["size"] for h in index.lookup("45X90")} == {"45X90"}
        assert len(index.lookup("45X90")) == 2

    def test_matches_on_category(self, index):
        assert [h["code"] for h in index.lookup("D4")] == ["C4"]

    def test_every_term_must_match(self, index):
        # Narrowing, not widening: "60X30 D2" is one tile, not every 60X30 tile
        # plus every D2 tile.
        assert [h["code"] for h in index.lookup("60X30 D2")] == ["C2"]
        assert index.lookup("45X90 D2") == [], "D2 is not a 45X90 tile"

    def test_exact_code_outranks_a_folder_match(self, index):
        # "C1" matches reference 1 by code; nothing should displace it from
        # first, because the code is the tile's identity.
        assert index.lookup("C1")[0]["code"] == "C1"

    def test_blank_query_returns_nothing_not_everything(self, index):
        assert index.lookup("") == []
        assert index.lookup("   ") == []

    def test_no_match_is_empty_not_an_error(self, index):
        assert index.lookup("NOSUCHTILE") == []

    def test_limit_is_honoured(self, index):
        assert len(index.lookup("45X90", limit=1)) == 1

    def test_results_carry_what_a_card_needs(self, index):
        h = index.lookup("C0")[0]
        # ref_id is what /reference/<id> is keyed on, so a hit with no ref_id is
        # a row staff cannot open the picture from.
        assert {"ref_id", "code", "size", "design", "thumb"} <= set(h)
        assert index.references[h["ref_id"]]["code"] == h["code"]

    def test_lookup_runs_no_inference(self, index, monkeypatch):
        # The search path must never touch the model: it is a different question
        # from a scan, and an accidental embed would make typing cost 650 ms.
        def boom(*a, **kw):
            raise AssertionError("lookup must not embed anything")

        monkeypatch.setattr(Matcher, "embed_query", boom)
        assert index.lookup("C0")
