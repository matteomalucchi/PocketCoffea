"""Unit tests for the jet pT-regression merging helper.

These mirror the pT-regression workflow check
(``test_full_configs/test_shape_variations/workflow_ptregr_check.py``), which
builds extra ``JetPtReg`` / ``JetPtRegPlusNeutrino`` collections from the ``Jet``
collection. Here we build small synthetic collections and validate that
``merge_regressed_jets`` combines them correctly. The b-tag cut is exercised in
all its configurations: no algorithm/WP given (default loose WP), a different
algorithm, a different WP, a manual raw-score cut, and no cut at all (plain
merge of regressed and non-regressed jets).
"""

import awkward as ak
import numpy as np
import pytest

from pocket_coffea.lib.jets import (
    get_btag_working_point,
    merge_regressed_jets,
    _resolve_btag_threshold,
)

# Minimal b-tagging parameters, in the two layouts supported by the helper.
# flat: btagging_WP: {L: ...}          (older-year layout, e.g. Run2)
FLAT_PARAMS = {
    "btagging": {
        "working_point": {
            "2018": {
                "btagging_algorithm": "btagDeepFlavB",
                "btagging_WP": {"L": 0.05, "M": 0.3, "T": 0.7},
            }
        }
    }
}
# nested-by-tagger: btagging_WP: {<tagger>: {L: ...}}
NESTED_PARAMS = {
    "btagging": {
        "working_point": {
            "2022_postEE": {
                "btagging_algorithm": "btagPNetB",
                "btagging_WP": {"btagPNetB": {"L": 0.05, "M": 0.3, "T": 0.7}},
            }
        }
    }
}
# two taggers available, default is btagPNetB; used to check that overriding the
# algorithm actually switches which discriminant the cut is applied to.
MULTI_PARAMS = {
    "btagging": {
        "working_point": {
            "2022_postEE": {
                "btagging_algorithm": "btagPNetB",
                "btagging_WP": {
                    "btagPNetB": {"L": 0.05, "M": 0.3},
                    "btagDeepFlavB": {"L": 0.05, "M": 0.3},
                },
            }
        }
    }
}


def _make_jets(pt_rows, btag_rows, src, algo):
    """Build a jagged jet collection tagging each jet with its origin (``src``).

    ``pt_rows``/``btag_rows`` are lists of lists (one inner list per event). A
    jet is "invalid" (regression failed) when its pt is <= 0.
    """
    return ak.Array(
        [
            [
                {"pt": float(p), "mass": float(p), algo: float(b), "src": src}
                for p, b in zip(pts, btags)
            ]
            for pts, btags in zip(pt_rows, btag_rows)
        ]
    )


# Two events; second event has a single jet. b-tag scores straddle the loose WP
# (0.05): jets 0 and 2 are "high b-tag", jet 1 and the last-event jet are low.
BTAG = [[0.9, 0.01, 0.3], [0.02]]
# standard JEC jets: always valid
STD = _make_jets([[10.0, 10.0, 10.0], [10.0]], BTAG, src=0, algo="btagDeepFlavB")
# regression without neutrinos: jet 1 and the last-event jet are invalid
NONU = _make_jets([[11.0, -1.0, 11.0], [-1.0]], BTAG, src=1, algo="btagDeepFlavB")
# regression with neutrinos: jets 1 and 2 invalid
NU = _make_jets([[12.0, -1.0, -1.0], [12.0]], BTAG, src=2, algo="btagDeepFlavB")


def _make_jets_2tag(pt_rows, pnet_rows, deepjet_rows, src):
    """Jets carrying two b-tag discriminants (btagPNetB, btagDeepFlavB)."""
    return ak.Array(
        [
            [
                {
                    "pt": float(p),
                    "mass": float(p),
                    "btagPNetB": float(a),
                    "btagDeepFlavB": float(b),
                    "src": src,
                }
                for p, a, b in zip(pts, pnet, deep)
            ]
            for pts, pnet, deep in zip(pt_rows, pnet_rows, deepjet_rows)
        ]
    )


def _src(jets):
    return jets["src"].tolist()


# --- reference implementations (the behaviour the helper must reproduce) -------
def _ref_first(std, reg):
    return ak.where(ak.nan_to_num(reg.pt, nan=-1) > 0, reg, std)


def _ref_second(std, reg, thr, tagger):
    return ak.where(
        (ak.nan_to_num(reg.pt, nan=-1) > 0) | (reg[tagger] >= thr), reg, std
    )


def _ref_neutrino_split(nonu, nu, default, thr, tagger):
    high = nonu[tagger] >= thr
    nu_valid = ak.nan_to_num(nu.pt, nan=-1) > 0
    plain_valid = ak.nan_to_num(nonu.pt, nan=-1) > 0
    low = ak.where(plain_valid, nonu, default)
    return ak.where(high & nu_valid, nu, low)


def test_get_btag_working_point_flat_and_nested():
    # flat layout: tagger taken from btagging_algorithm, WP read directly
    assert get_btag_working_point(FLAT_PARAMS, "2018") == ("btagDeepFlavB", 0.05)
    assert get_btag_working_point(FLAT_PARAMS, "2018", "M") == ("btagDeepFlavB", 0.3)
    # nested layout: WP read from the per-tagger sub-dict
    assert get_btag_working_point(NESTED_PARAMS, "2022_postEE") == ("btagPNetB", 0.05)
    assert get_btag_working_point(NESTED_PARAMS, "2022_postEE", "T") == (
        "btagPNetB",
        0.7,
    )


def test_resolve_btag_threshold_score_and_wp():
    # explicit raw score keeps the tagger from parameters
    assert _resolve_btag_threshold(FLAT_PARAMS, "2018", btag_score=0.42) == (
        "btagDeepFlavB",
        0.42,
    )
    # working point resolves to its numeric threshold
    assert _resolve_btag_threshold(FLAT_PARAMS, "2018", btag_wp="M") == (
        "btagDeepFlavB",
        0.3,
    )
    # algorithm override is respected
    tagger, _ = _resolve_btag_threshold(
        NESTED_PARAMS, "2022_postEE", btag_algorithm="btagPNetB", btag_wp="L"
    )
    assert tagger == "btagPNetB"


def test_merge_no_btag_cut_uses_regression_where_valid():
    # single fallback chain, no b-tag cut: regressed jet where valid, else standard
    out = merge_regressed_jets([NONU, STD])
    assert _src(out) == _src(_ref_first(STD, NONU))
    assert _src(out) == [[1, 0, 1], [0]]  # jet 1 / last-event jet fall back to std


def test_merge_second_approach_high_btag_forced():
    # high b-tag jets always take the regression (even if invalid pt), the rest
    # take the regression where valid, else standard. threshold = loose WP.
    out = merge_regressed_jets(NONU, [NONU, STD], FLAT_PARAMS, "2018")
    ref = _ref_second(STD, NONU, 0.05, "btagDeepFlavB")
    assert _src(out) == _src(ref)
    # jet 2 is high b-tag but its regression is invalid -> still regressed (src 1)
    assert _src(out) == [[1, 0, 1], [0]]


def test_merge_neutrino_split_by_btag():
    # +neutrino regression for high b-tag jets, plain regression for the rest,
    # each with a fallback chain ending on the standard jets.
    out = merge_regressed_jets(
        [NU, NONU, STD],
        [NONU, STD],
        params=FLAT_PARAMS,
        year="2018",
    )
    ref = _ref_neutrino_split(NONU, NU, STD, 0.05, "btagDeepFlavB")
    assert _src(out) == _src(ref)
    # event 0: jet0 high+nu-valid -> nu(2); jet1 low, nonu invalid -> std(0);
    #          jet2 high, nu invalid, nonu valid -> nonu(1)
    # event 1: jet low, nonu invalid -> std(0)
    assert _src(out) == [[2, 0, 1], [0]]


# --- the five configuration cases requested for the b-tag cut -----------------
def test_case_no_algorithm_or_wp_defined_uses_default_loose_wp():
    # Case: user defines neither the b-tag algorithm nor the WP.
    # -> tagger comes from btagging_algorithm, threshold is the loose ("L") WP.
    assert _resolve_btag_threshold(FLAT_PARAMS, "2018") == ("btagDeepFlavB", 0.05)
    assert _resolve_btag_threshold(NESTED_PARAMS, "2022_postEE") == ("btagPNetB", 0.05)
    # and the merge with no algo/wp given matches an explicit loose-WP cut
    default = merge_regressed_jets(NONU, [NONU, STD], FLAT_PARAMS, "2018")
    explicit_L = merge_regressed_jets(NONU, [NONU, STD], FLAT_PARAMS, "2018", btag_wp="L")
    assert _src(default) == _src(explicit_L)


def test_case_different_btag_algorithm():
    # Case: user picks a b-tag algorithm different from the parameters' default.
    # The jet is high on btagPNetB (0.9) but low on btagDeepFlavB (0.01); its
    # regression is invalid, so it is only kept (forced) when it counts as high.
    std = _make_jets_2tag([[10.0]], [[0.9]], [[0.01]], src=0)
    reg = _make_jets_2tag([[-1.0]], [[0.9]], [[0.01]], src=1)
    # default algorithm (btagPNetB): high b-tag -> forced regressed
    out_default = merge_regressed_jets(reg, [reg, std], MULTI_PARAMS, "2022_postEE")
    assert _src(out_default) == [[1]]
    # override to btagDeepFlavB: now low b-tag, regression invalid -> standard
    out_deepjet = merge_regressed_jets(
        reg, [reg, std], MULTI_PARAMS, "2022_postEE", btag_algorithm="btagDeepFlavB"
    )
    assert _src(out_deepjet) == [[0]]


def test_case_different_btag_wp():
    # Case: user picks a WP different from the default loose one. A jet with
    # discriminant 0.2 is high under L (0.05) but low under M (0.3).
    std = _make_jets([[10.0]], [[0.2]], src=0, algo="btagDeepFlavB")
    reg = _make_jets([[-1.0]], [[0.2]], src=1, algo="btagDeepFlavB")  # invalid regr.
    out_L = merge_regressed_jets(reg, [reg, std], FLAT_PARAMS, "2018", btag_wp="L")
    out_M = merge_regressed_jets(reg, [reg, std], FLAT_PARAMS, "2018", btag_wp="M")
    assert _src(out_L) == [[1]]  # high under loose -> forced regressed
    assert _src(out_M) == [[0]]  # low under medium -> standard


def test_case_manual_btag_score_cut():
    # Case: user passes a raw b-tag discriminant threshold. Jet discriminant 0.2.
    std = _make_jets([[10.0]], [[0.2]], src=0, algo="btagDeepFlavB")
    reg = _make_jets([[-1.0]], [[0.2]], src=1, algo="btagDeepFlavB")  # invalid regr.
    below = merge_regressed_jets(reg, [reg, std], FLAT_PARAMS, "2018", btag_score=0.1)
    above = merge_regressed_jets(reg, [reg, std], FLAT_PARAMS, "2018", btag_score=0.3)
    assert _src(below) == [[1]]  # 0.2 >= 0.1 -> high -> forced regressed
    assert _src(above) == [[0]]  # 0.2 <  0.3 -> low  -> standard


def test_case_no_btag_cut_just_merges_regressed_and_standard():
    # Case: no b-tag cut requested (jets_low_btag omitted): simply merge the
    # regressed jets with the non-regressed ones, using the regression where valid.
    out = merge_regressed_jets([NONU, STD])
    assert _src(out) == _src(_ref_first(STD, NONU))
    assert _src(out) == [[1, 0, 1], [0]]


def test_wp_and_equivalent_score_agree():
    out_wp = merge_regressed_jets(NONU, [NONU, STD], FLAT_PARAMS, "2018", btag_wp="M")
    out_score = merge_regressed_jets(
        NONU, [NONU, STD], FLAT_PARAMS, "2018", btag_score=0.3
    )
    assert _src(out_wp) == _src(out_score)


def test_nested_layout_and_algorithm_override():
    nonu = _make_jets([[11.0, -1.0], [11.0]], [[0.9, 0.01], [0.02]], 1, "btagPNetB")
    std = _make_jets([[10.0, 10.0], [10.0]], [[0.9, 0.01], [0.02]], 0, "btagPNetB")
    out = merge_regressed_jets(
        nonu,
        [nonu, std],
        params=NESTED_PARAMS,
        year="2022_postEE",
        btag_algorithm="btagPNetB",
        btag_wp="L",
    )
    ref = _ref_second(std, nonu, 0.05, "btagPNetB")
    assert _src(out) == _src(ref)


def test_btag_wp_and_score_are_mutually_exclusive():
    with pytest.raises(ValueError):
        merge_regressed_jets(
            NONU, [NONU, STD], FLAT_PARAMS, "2018", btag_wp="M", btag_score=0.3
        )


def test_merged_pt_is_taken_from_selected_collection():
    # sanity check that whole records (not only src) are picked consistently
    out = merge_regressed_jets([NONU, STD])
    pt = ak.to_numpy(ak.flatten(out.pt))
    src = ak.to_numpy(ak.flatten(out["src"]))
    # regressed jets keep pt 11, jets falling back to standard keep pt 10
    assert np.all(pt[src == 1] == 11.0)
    assert np.all(pt[src == 0] == 10.0)
