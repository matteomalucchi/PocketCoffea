import numpy as np
import awkward as ak
import correctionlib
import correctionlib.schemav2 as cs
import pytest

from pocket_coffea.lib.trigger_sf import (
    get_trigger_sf_variable,
    sf_trigger,
    trigger_sf_variables,
)
from pocket_coffea.lib.triggers import (
    get_trigger_object_matching_mask,
    get_trigger_object_matching_masks,
)


def build_correction(name, variable, edges, content):
    '''Correction with the same structure produced by the conversion script'''
    return cs.Correction(
        name=name,
        version=1,
        inputs=[
            cs.Variable(name="systematic", type="string"),
            cs.Variable(name=variable, type="real"),
        ],
        output=cs.Variable(name="weight", type="real"),
        data=cs.Category(
            nodetype="category",
            input="systematic",
            content=[
                cs.CategoryItem(
                    key=systematic,
                    value=cs.Binning(
                        nodetype="binning",
                        input=variable,
                        edges=list(edges),
                        content=list(values),
                        flow="clamp",
                    ),
                )
                for systematic, values in content.items()
            ],
        ),
    )


@pytest.fixture(scope="module")
def correction_file(tmp_path_factory):
    '''Correctionlib file with the scale factors of two trigger filters'''
    correction_set = cs.CorrectionSet(
        schema_version=2,
        corrections=[
            build_correction(
                "sf_L1All",
                "calojet_ht",
                [0.0, 100.0, 200.0, 300.0],
                {
                    "nominal": [0.5, 0.9, 1.0],
                    "up": [0.6, 0.95, 1.1],
                    "down": [0.4, 0.85, 0.9],
                },
            ),
            build_correction(
                "sf_1PFCentralJetTightIDPt70",
                "jet_pt",
                [0.0, 50.0, 100.0],
                {
                    "nominal": [0.8, 1.0],
                    "up": [0.9, 1.2],
                    "down": [0.7, 0.8],
                },
            ),
        ],
    )
    path = tmp_path_factory.mktemp("trigger_sf") / "trigger_sf.json"
    path.write_text(correction_set.model_dump_json(exclude_unset=True))
    return str(path)


@pytest.fixture(scope="module")
def events():
    '''Synthetic events with jets, muons and trigger objects'''
    jets = ak.zip(
        {
            # the collection is sorted by b-tagging score, not by pt
            "pt": [[40.0, 120.0, 35.0, 25.0], [80.0, 60.0], [200.0, 10.0]],
            "eta": [[0.0, 1.0, -1.0, 3.0], [0.0, 0.5], [0.0, 0.0]],
            "phi": [[0.0, 1.0, 2.0, 3.0], [0.0, 1.0], [0.0, 3.0]],
            "muEF": [[0.0, 0.0, 0.9, 0.0], [0.0, 0.0], [0.0, 0.0]],
            "chEmEF": [[0.0, 0.0, 0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
            "neEmEF": [[0.0, 0.0, 0.0, 0.0], [0.0, 0.0], [0.0, 0.0]],
            "btagPNetB": [[0.9, 0.8, 0.5, 0.1], [0.99, 0.01], [0.5, 0.5]],
        }
    )
    muons = ak.zip(
        {
            # the first muon overlaps with the first jet of the first event
            "pt": [[30.0], [], []],
            "eta": [[0.05], [], []],
            "phi": [[0.05], [], []],
            "pfRelIso04_all": [[0.05], [], []],
        }
    )
    trigobj = ak.zip(
        {
            "id": [[1, 1, 1, 3], [1, 1], [3]],
            "eta": [[0.0, 1.0, -1.0, 0.0], [0.0, 0.5], [0.0]],
            "phi": [[0.0, 1.0, 2.0, 0.0], [0.0, 1.0], [0.0]],
            # bit 0 for all the jet objects, bit 5 for the HT objects
            "filterBits": [[1, 1, 1, 32], [1, 1], [32]],
        }
    )
    return ak.zip(
        {"Jet": jets, "JetGood": jets, "Muon": muons, "TrigObj": trigobj},
        depth_limit=1,
    )


def test_registered_variables():
    for variable in ["jet_pt", "alljet_ht", "calojet_ht", "atanh_btag_mean"]:
        assert variable in trigger_sf_variables


def test_jet_pt(events):
    # the collection is sorted by b-tagging score: the jets have to be sorted by pt
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "jet_pt", "index": 1}),
        [120.0, 80.0, 200.0],
    )
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "jet_pt", "index": 2}),
        [40.0, 60.0, 10.0],
    )
    # events with less than `index` jets are filled with the padding value
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "jet_pt", "index": 4}),
        [25.0, 0.0, 0.0],
    )
    assert np.allclose(
        get_trigger_sf_variable(
            events, {"name": "jet_pt", "index": 4, "pad_value": -1.0}
        ),
        [25.0, -1.0, -1.0],
    )


def test_alljet_ht(events):
    # only the jets with pt >= 30 and |eta| < 2.5 are considered
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "alljet_ht"}),
        [40.0 + 120.0 + 35.0, 80.0 + 60.0, 200.0],
    )


def test_calojet_ht(events):
    # the first jet of the first event is close to an isolated muon and has a small
    # muon/EM energy fraction: it is not included in the Calo-HT.
    # The third jet is close to no muon (and has muEF > 0.5): it is included.
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "calojet_ht"}),
        [120.0 + 35.0, 80.0 + 60.0, 200.0],
    )
    # if the muon is not isolated the jet is not identified as a muon
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "calojet_ht", "muon_iso": 0.0}),
        [40.0 + 120.0 + 35.0, 80.0 + 60.0, 200.0],
    )


def test_atanh_btag_mean(events):
    assert np.allclose(
        get_trigger_sf_variable(events, {"name": "atanh_btag_mean"}),
        np.arctanh([(0.9 + 0.8) / 2, (0.99 + 0.01) / 2, (0.5 + 0.5) / 2]),
    )
    # the score is clipped to avoid infinities
    assert np.isfinite(
        get_trigger_sf_variable(
            events, {"name": "atanh_btag_mean", "n": 1, "field": "btagPNetB"}
        )
    ).all()


def test_sf_trigger(events, correction_file):
    params = {
        "trigger_scale_factors": {
            "2022_postEE": {
                "file": correction_file,
                "corrections": [
                    {"name": "sf_L1All", "variable": {"name": "calojet_ht"}},
                    {
                        "name": "sf_1PFCentralJetTightIDPt70",
                        "variable": {"name": "jet_pt", "index": 1},
                    },
                ],
            }
        }
    }
    sf, up, down = sf_trigger(params, events, "2022_postEE")

    # calojet_ht = [155, 140, 200] --> L1 SF = [0.9, 0.9, 1.0]
    # leading jet pt = [120, 80, 200] --> jet SF = [1.0, 1.0, 1.0] (flow clamped)
    assert np.allclose(sf, [0.9 * 1.0, 0.9 * 1.0, 1.0 * 1.0])
    assert np.allclose(up, [0.95 * 1.2, 0.95 * 1.2, 1.1 * 1.2])
    assert np.allclose(down, [0.85 * 0.8, 0.85 * 0.8, 0.9 * 0.8])

    # the scale factor is the same if the correction set is loaded externally
    sf_2, _, _ = sf_trigger(
        params,
        events,
        "2022_postEE",
        correction_set=correctionlib.CorrectionSet.from_file(correction_file),
    )
    assert np.allclose(sf, sf_2)


def test_sf_trigger_missing_config(events):
    with pytest.raises(Exception):
        sf_trigger({}, events, "2022_postEE")
    with pytest.raises(Exception):
        sf_trigger({"trigger_scale_factors": {}}, events, "2018")


def test_trigger_object_matching(events):
    # 4 jet objects passing the bit 0 in the first event, 2 in the second one
    filters = {"trigger_4jets": ["1:0:4:20:4PFCentralJetTightIDPt20"]}
    masks = get_trigger_object_matching_masks(events, filters, collection="JetGood")
    # first event: 3 trigger objects with id 1 are matched to a jet (the fourth
    # object has id 3 and is not considered) --> less than the 4 required
    assert list(masks["trigger_4jets"]) == [False, False, False]

    filters = {"trigger_3jets": ["1:0:3:20:3PFCentralJetTightIDPt20"]}
    masks = get_trigger_object_matching_masks(events, filters, collection="JetGood")
    assert list(masks["trigger_3jets"]) == [True, False, False]

    # HT filters are not matched to the offline objects
    filters = {"trigger_ht": ["3:5:0:280:PFHT280Jet30"]}
    masks = get_trigger_object_matching_masks(events, filters, collection="JetGood")
    assert list(masks["trigger_ht"]) == [True, False, True]

    # the OR of the triggers is returned
    filters = {
        "trigger_3jets": ["1:0:3:20:3PFCentralJetTightIDPt20"],
        "trigger_ht": ["3:5:0:280:PFHT280Jet30"],
    }
    assert list(get_trigger_object_matching_mask(events, filters)) == [True, False, True]
    assert list(
        get_trigger_object_matching_mask(events, filters, triggers=["trigger_3jets"])
    ) == [True, False, False]

    # the AND of the filters of the same trigger is required
    filters = {
        "trigger": ["1:0:3:20:3PFCentralJetTightIDPt20", "3:5:0:280:PFHT280Jet30"]
    }
    assert list(get_trigger_object_matching_mask(events, filters)) == [
        True,
        False,
        False,
    ]

    # without the offline matching only the number of trigger objects is required
    filters = {"trigger_2jets": ["1:0:2:20:2PFCentralJetTightIDPt20"]}
    masks = get_trigger_object_matching_masks(
        events, filters, collection="JetGood", match_objects=False
    )
    assert list(masks["trigger_2jets"]) == [True, True, False]

    with pytest.raises(Exception):
        get_trigger_object_matching_mask(events, filters, triggers=["not_configured"])
