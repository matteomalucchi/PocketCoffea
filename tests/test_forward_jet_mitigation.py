"""Offline unit tests for the forward jet mitigation (no EOS / proxy needed).

Covers the resolution of the `forward_jet_mitigation` parameters, the object-level
veto of the low-pT forward-endcap jets and the two calibration-level mitigations,
i.e. dropping the JER smearing and undoing the L2L3Residual correction inside an
|eta| window.
"""
import os

import numpy as np
import awkward as ak
import pytest
from omegaconf import OmegaConf

import correctionlib
from correctionlib.schemav2 import Correction, CorrectionSet

from pocket_coffea.lib.jets import (
    eta_window_mask,
    forward_jet_veto_mask,
    get_forward_jet_mitigation,
    remove_residual_correction,
)
import pocket_coffea.parameters as parameters_module

SHIPPED_DEFAULTS = os.path.join(
    os.path.dirname(parameters_module.__file__), "forward_jet_mitigation.yaml"
)


def _params(**overrides):
    """Parameters holding only the mitigation block, with the shipped defaults."""
    params = OmegaConf.create(
        {
            "forward_jet_mitigation": {
                "jet_veto": {
                    "enabled": False,
                    "eta_min": 2.5,
                    "eta_max": 3.0,
                    "pt_min": 50.0,
                    "by_year": {},
                },
                "skip_jer": {
                    "enabled": False,
                    "eta_min": 2.5,
                    "eta_max": 5.191,
                    "by_year": {},
                },
                "skip_residual": {
                    "enabled": False,
                    "eta_min": 3.0,
                    "eta_max": 5.191,
                    "by_year": {},
                },
            }
        }
    )
    for key, value in overrides.items():
        OmegaConf.update(params, f"forward_jet_mitigation.{key}", value, merge=True)
    return params


def _jets(pt, eta):
    return ak.zip({"pt": ak.Array(pt), "eta": ak.Array(eta)})


# --------------------------------------------------------------------------- #
# Parameter resolution
# --------------------------------------------------------------------------- #

def test_every_mitigation_is_off_in_the_shipped_defaults():
    """The defaults shipped with the package must never change an analysis silently."""
    params = OmegaConf.load(SHIPPED_DEFAULTS)
    for block in ("jet_veto", "skip_jer", "skip_residual"):
        assert params.forward_jet_mitigation[block].enabled is False
        for year in ("2018", "2022_preEE", "2023_postBPix", "2024"):
            assert get_forward_jet_mitigation(params, block, year) is None


def test_the_test_fixture_matches_the_shipped_defaults():
    """Guards the fixture used by the rest of the suite against drifting from the YAML."""
    assert _params() == OmegaConf.load(SHIPPED_DEFAULTS)


def test_block_is_resolved_when_enabled():
    cfg = get_forward_jet_mitigation(
        _params(jet_veto={"enabled": True}), "jet_veto", "2022_preEE"
    )
    assert cfg == {"enabled": True, "eta_min": 2.5, "eta_max": 3.0, "pt_min": 50.0}


def test_by_year_enables_a_single_period():
    params = _params(skip_jer={"by_year": {"2022_preEE": {"enabled": True}}})
    assert get_forward_jet_mitigation(params, "skip_jer", "2022_preEE") is not None
    assert get_forward_jet_mitigation(params, "skip_jer", "2023_preBPix") is None


def test_by_year_overrides_the_window_of_a_single_period():
    params = _params(
        skip_residual={
            "enabled": True,
            "by_year": {"2022_preEE": {"eta_min": 2.5, "eta_max": 4.0}},
        }
    )
    tuned = get_forward_jet_mitigation(params, "skip_residual", "2022_preEE")
    default = get_forward_jet_mitigation(params, "skip_residual", "2023_preBPix")
    assert (tuned["eta_min"], tuned["eta_max"]) == (2.5, 4.0)
    assert (default["eta_min"], default["eta_max"]) == (3.0, 5.191)


def test_enabled_argument_overrides_the_parameters_both_ways():
    off, on = _params(), _params(jet_veto={"enabled": True})
    assert get_forward_jet_mitigation(off, "jet_veto", "2022_preEE", enabled=True) is not None
    assert get_forward_jet_mitigation(on, "jet_veto", "2022_preEE", enabled=False) is None


def test_missing_block_is_silently_off_but_raises_when_requested():
    empty = OmegaConf.create({})
    assert get_forward_jet_mitigation(empty, "jet_veto", "2022_preEE") is None
    assert get_forward_jet_mitigation(None, "jet_veto", "2022_preEE") is None
    with pytest.raises(ValueError, match="jet_veto"):
        get_forward_jet_mitigation(empty, "jet_veto", "2022_preEE", enabled=True)


# --------------------------------------------------------------------------- #
# Object-level veto
# --------------------------------------------------------------------------- #

def test_veto_is_a_no_op_when_disabled():
    jets = _jets([[30.0, 100.0]], [[2.7, 2.7]])
    assert forward_jet_veto_mask(jets, _params(), "2022_preEE") is True


def test_veto_rejects_only_the_low_pt_forward_endcap_jets():
    #            below window   in window, soft   in window, hard   above window
    jets = _jets(
        [[30.0, 100.0], [30.0, 100.0], [30.0]],
        [[2.4, 2.4], [2.7, 2.7], [3.5]],
    )
    mask = forward_jet_veto_mask(jets, _params(jet_veto={"enabled": True}), "2022_preEE")
    assert ak.to_list(mask) == [[True, True], [False, True], [True]]


def test_veto_window_edges_are_closed_below_and_open_above():
    jets = _jets([[10.0, 10.0, 10.0]], [[2.5, 3.0, -2.5]])
    mask = forward_jet_veto_mask(jets, _params(jet_veto={"enabled": True}), "2022_preEE")
    # 2.5 is inside the window, 3.0 is not, and the veto is symmetric in eta
    assert ak.to_list(mask) == [[False, True, False]]


def test_veto_can_cut_on_an_alternative_pt():
    jets = _jets([[30.0]], [[2.7]])
    params = _params(jet_veto={"enabled": True})
    regressed = ak.Array([[80.0]])
    assert ak.to_list(forward_jet_veto_mask(jets, params, "2022_preEE")) == [[False]]
    assert ak.to_list(forward_jet_veto_mask(jets, params, "2022_preEE", pt=regressed)) == [[True]]


def test_veto_honours_the_call_level_flag():
    jets = _jets([[30.0]], [[2.7]])
    on, off = _params(jet_veto={"enabled": True}), _params()
    assert ak.to_list(forward_jet_veto_mask(jets, off, "2022_preEE", enabled=True)) == [[False]]
    assert forward_jet_veto_mask(jets, on, "2022_preEE", enabled=False) is True


# --------------------------------------------------------------------------- #
# Calibration-level mitigations
# --------------------------------------------------------------------------- #

def test_eta_window_mask_is_symmetric_and_half_open():
    eta = np.array([0.0, -2.6, 2.6, 3.0, -3.0, 4.0])
    cfg = {"eta_min": 2.5, "eta_max": 3.0}
    assert eta_window_mask(eta, cfg).tolist() == [False, True, True, False, False, False]


def test_skipping_the_jer_leaves_the_window_unsmeared():
    """The JER skip is a `where` on the smearing factor, reproduced here on its own."""
    eta = np.array([1.0, 2.6, 4.0])
    jersmear = np.array([1.10, 1.20, 1.30])
    cfg = {"eta_min": 2.5, "eta_max": 5.191}
    assert np.where(eta_window_mask(eta, cfg), 1.0, jersmear).tolist() == [1.10, 1.0, 1.0]


def _residual_cset(tag, values):
    """A JERC-like correction set with a standalone L2L3Residual binned in |eta|."""
    corr = Correction.model_validate(
        {
            "name": tag,
            "version": 1,
            "inputs": [
                {"name": "JetEta", "type": "real"},
                {"name": "JetPt", "type": "real"},
            ],
            "output": {"name": "correction", "type": "real"},
            "data": {
                "nodetype": "binning",
                "input": "JetEta",
                "edges": [-5.2, -3.0, 3.0, 5.2],
                "content": list(values),
                "flow": "clamp",
            },
        }
    )
    cset = CorrectionSet.model_validate(
        {"schema_version": 2, "corrections": [corr]}
    )
    return correctionlib.CorrectionSet.from_string(cset.model_dump_json())


def test_removing_the_residual_only_touches_the_window():
    tag, jec_tag, jet_type = "TEST_DATA_L2L3Residual_AK4PFPuppi", "TEST_DATA", "AK4PFPuppi"
    # residual of 1.25 in the HF region, 1.0 in the barrel/endcap
    cset = _residual_cset(tag, [1.25, 1.0, 1.25])
    eta = np.array([1.0, 4.0])
    pt_raw = np.array([100.0, 100.0])
    jes_factor = np.array([1.10, 1.10 * 1.25])
    cfg = {"eta_min": 3.0, "eta_max": 5.191}

    out = remove_residual_correction(cset, jec_tag, jet_type, eta, pt_raw, jes_factor, cfg)
    # the central jet keeps its factor, the forward one loses the 1.25 residual
    np.testing.assert_allclose(out, [1.10, 1.10])


def test_removing_the_residual_raises_when_the_file_has_no_standalone_residual():
    cset = _residual_cset("OTHER_DATA_L2L3Residual_AK4PFPuppi", [1.0, 1.0, 1.0])
    with pytest.raises(Exception, match="L2L3Residual"):
        remove_residual_correction(
            cset,
            "TEST_DATA",
            "AK4PFPuppi",
            np.array([4.0]),
            np.array([100.0]),
            np.array([1.0]),
            {"eta_min": 3.0, "eta_max": 5.191},
        )


# --------------------------------------------------------------------------- #
# Integration with jet_selection
# --------------------------------------------------------------------------- #

class _Events:
    """Minimal stand-in for a NanoEvents chunk: collections plus chunk metadata."""

    def __init__(self, collections, metadata):
        self._collections = dict(collections)
        self.metadata = metadata

    def __getitem__(self, key):
        return self._collections[key]

    def __setitem__(self, key, value):
        self._collections[key] = value


def _selection_setup(**overrides):
    params = _params(**overrides)
    params = OmegaConf.merge(
        params,
        OmegaConf.create(
            {
                "object_preselection": {"Jet": {"pt": 20.0, "eta": 4.7, "jetId": 2}},
                "default_nano_version": {"2022_preEE": 9},
            }
        ),
    )
    jets = ak.zip(
        {
            # one central jet, one soft and one hard forward-endcap jet, one HF jet
            "pt": ak.Array([[100.0, 30.0, 100.0, 30.0]]),
            "eta": ak.Array([[0.5, 2.7, 2.7, 3.5]]),
            "jetId": ak.Array([[6, 6, 6, 6]]),
        }
    )
    # nano_version 9 keeps the jetId as stored, no recomputation needed here
    events = _Events({"Jet": jets}, {"nano_version": "9", "isMC": True})
    return events, params


def test_jet_selection_ignores_the_veto_by_default():
    from pocket_coffea.lib.jets import jet_selection

    events, params = _selection_setup()
    _, mask = jet_selection(events, "Jet", params, "2022_preEE")
    assert ak.to_list(mask) == [[True, True, True, True]]


def test_jet_selection_applies_the_veto_enabled_in_the_parameters():
    from pocket_coffea.lib.jets import jet_selection

    events, params = _selection_setup(jet_veto={"enabled": True})
    good, mask = jet_selection(events, "Jet", params, "2022_preEE")
    # only the soft forward-endcap jet is dropped
    assert ak.to_list(mask) == [[True, False, True, True]]
    assert ak.to_list(good.eta) == [[0.5, 2.7, 3.5]]


def test_jet_selection_flag_overrides_the_parameters():
    from pocket_coffea.lib.jets import jet_selection

    events, params = _selection_setup()
    _, mask = jet_selection(events, "Jet", params, "2022_preEE", forward_jet_veto=True)
    assert ak.to_list(mask) == [[True, False, True, True]]

    events, params = _selection_setup(jet_veto={"enabled": True})
    _, mask = jet_selection(events, "Jet", params, "2022_preEE", forward_jet_veto=False)
    assert ak.to_list(mask) == [[True, True, True, True]]
