"""Size filtering and the display match bar.

These two are the only things standing between "the user declared 45X90" and a
60X30 reference winning the scan, so they are tested against a synthetic index
rather than the real one — the real index takes 20 minutes to build and its
contents would make the assertions depend on the catalogue.
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


class TestDisplayToggles:
    """The score toggle is display-only and must stay that way.

    Hiding the percentage from staff must never remove it from the API or the
    log — that is the difference between a display setting and losing the ability
    to debug a scan.
    """

    def test_show_score_defaults_on(self, monkeypatch):
        import importlib

        from tilematch import server

        monkeypatch.delenv("TILEMATCH_SHOW_SCORE", raising=False)
        assert importlib.reload(server).SHOW_SCORE is True

    def test_show_score_off_by_env(self, monkeypatch):
        import importlib

        from tilematch import server

        monkeypatch.setenv("TILEMATCH_SHOW_SCORE", "0")
        reloaded = importlib.reload(server)
        try:
            assert reloaded.SHOW_SCORE is False
        finally:
            monkeypatch.delenv("TILEMATCH_SHOW_SCORE")
            importlib.reload(server)

    def test_score_survives_in_the_payload(self, index, monkeypatch):
        # Whatever the page shows, the candidate dict always carries the score.
        fake_query(index, 0, monkeypatch)
        assert "score" in index.search(None, k=1)[0].as_dict()

    def test_build_stamp_tracks_display_config(self, monkeypatch):
        # A stamp that missed the toggle would report "current" while the page
        # showed something else.
        import importlib

        from tilematch import server

        on = importlib.reload(server).build_stamp()
        monkeypatch.setenv("TILEMATCH_SHOW_SCORE", "0")
        try:
            assert importlib.reload(server).build_stamp() != on
        finally:
            monkeypatch.delenv("TILEMATCH_SHOW_SCORE")
            importlib.reload(server)
