"""The source tree's real quirks, pinned as tests.

Every case here was observed in poc/Tiles/, not invented.
"""

from tilematch.catalog import clean_code, extract_face, normalize_folder


class TestCleanCode:
    def test_strips_copy_prefix_and_extension(self):
        assert clean_code("Copy of RP.CMA.0001DJ.SM.0T.jpg") == "RP.CMA.0001DJ.SM.0T"

    def test_prefix_is_conditional(self):
        # Only 95 of 133 files carry it; the rest must pass through untouched.
        assert clean_code("11DH.MA_F1.jpg") == "11DH.MA_F1"

    def test_double_dot_extension_leaves_no_trailing_dot(self):
        # Real file: naive rsplit('.', 1) yields "RP.HTC.0001DC.MA.0T."
        assert clean_code("Copy of RP.HTC.0001DC.MA.0T..jpg") == "RP.HTC.0001DC.MA.0T"

    def test_trailing_space_before_extension(self):
        assert clean_code("279 .jpg") == "279"
        assert clean_code("Copy of 11B Solid White .tif") == "11B Solid White"

    def test_tif_is_handled(self):
        assert clean_code("Copy of 4CC  Cotto   Red.tif") == "4CC  Cotto   Red"


class TestNormalizeFolder:
    def test_strips_stray_whitespace(self):
        # All three are real folder names in the tree.
        assert normalize_folder(" SYLVORA") == "SYLVORA"
        assert normalize_folder("ARKE ") == "ARKE"
        assert normalize_folder("IMPERIAL ") == "IMPERIAL"

    def test_case_and_inner_whitespace(self):
        assert normalize_folder("Crema  Marmol") == "CREMA MARMOL"

    def test_size_folders_unchanged(self):
        assert normalize_folder("45X90") == "45X90"


class TestExtractFace:
    def test_structured_code(self):
        assert extract_face("RP.CMA.0008DJ.SM.0T") == "8"

    def test_face_suffix(self):
        assert extract_face("77DH.MA_F3") == "3"

    def test_bare_face_number(self):
        assert extract_face("1Jk") == "1"
        assert extract_face("61M") == "61"

    def test_bare_integer(self):
        assert extract_face("279") == "279"

    def test_free_text_after_code(self):
        assert extract_face("6LD.MA Quarry Stone Natural") == "6"

    def test_returns_none_rather_than_guessing(self):
        # Dash-delimited FLUTE names carry no recoverable face number.
        assert extract_face("RC-001-OHA-156-MA-J2") is None
