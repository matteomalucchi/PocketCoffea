import numpy as np
import awkward as ak
import correctionlib
import correctionlib.schemav2 as cs
import pytest

from pocket_coffea.lib.trigger_sf import (
    get_trigger_sf_variable,
    register_trigger_sf_variable,
    sf_trigger,
)
from pocket_coffea.lib.triggers import (
    get_trigger_object_matching_mask,
    get_trigger_object_matching_masks,
)


# Trigger scale factor observables are analysis-specific (e.g. the jet-trigger
# ones used by the HH4b analysis live in AnalysisConfigs, registered with
# `register_trigger_sf_variable`): these tests only exercise the generic
# registration/application machinery with a couple of minimal, self-contained
# observables, not shipped with PocketCoffea itself.
@register_trigger_sf_variable("_test_n_jets")
def _test_n_jets(events, cfg):
    return ak.num(events[cfg.get("collection", "JetGood")], axis=1)


@register_trigger_sf_variable("_test_leading_jet_pt")
def _test_leading_jet_pt(events, cfg):
    return ak.fill_none(
        ak.firsts(events[cfg.get("collection", "JetGood")].pt), 0.0
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
                "sf_A",
                "_test_n_jets",
                [0.0, 3.0, 5.0],
                {
                    "nominal": [0.5, 0.9],
                    "up": [0.6, 0.95],
                    "down": [0.4, 0.85],
                },
            ),
            build_correction(
                "sf_B",
                "_test_leading_jet_pt",
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
    '''Synthetic events with jets and trigger objects'''
    jets = ak.zip(
        {
            "pt": [[120.0, 40.0, 35.0, 25.0], [80.0, 60.0], [200.0, 10.0]],
            "eta": [[0.0, 1.0, -1.0, 3.0], [0.0, 0.5], [0.0, 0.0]],
            "phi": [[0.0, 1.0, 2.0, 3.0], [0.0, 1.0], [0.0, 3.0]],
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
        {"Jet": jets, "JetGood": jets, "TrigObj": trigobj},
        depth_limit=1,
    )


def test_sf_trigger(events, correction_file):
    params = {
        "trigger_scale_factors": {
            "2022_postEE": {
                "file": correction_file,
                "corrections": [
                    {"name": "sf_A", "variable": {"name": "_test_n_jets"}},
                    {"name": "sf_B", "variable": {"name": "_test_leading_jet_pt"}},
                ],
            }
        }
    }
    sf, up, down = sf_trigger(params, events, "2022_postEE")

    # n_jets = [4, 2, 2] --> sf_A = [0.9, 0.5, 0.5]
    # leading jet pt = [120, 80, 200] --> sf_B = [1.0, 1.0, 1.0] (flow clamped)
    assert np.allclose(sf, [0.9 * 1.0, 0.5 * 1.0, 0.5 * 1.0])
    assert np.allclose(up, [0.95 * 1.2, 0.6 * 1.2, 0.6 * 1.2])
    assert np.allclose(down, [0.85 * 0.8, 0.4 * 0.8, 0.4 * 0.8])

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


def test_get_trigger_sf_variable_unknown():
    with pytest.raises(Exception):
        get_trigger_sf_variable(None, {"name": "not_registered"})


OBJECT_TYPES = {
    "Jet": {"id": 1, "matchable": True, "default_collection": "JetGood"},
    "HT": {"id": 3, "matchable": False, "default_collection": None},
    "Electron": {"id": 11, "matchable": True, "default_collection": "ElectronGood"},
}


def test_trigger_object_matching(events):
    # 4 jet objects passing the bit 0 in the first event, 2 in the second one
    filters = {"trigger_4jets": ["Jet:0:4:20:4PFCentralJetTightIDPt20"]}
    masks = get_trigger_object_matching_masks(events, filters, OBJECT_TYPES)
    # first event: 3 trigger objects with id 1 are matched to a jet (the fourth
    # object has id 3 and is not considered) --> less than the 4 required
    assert list(masks["trigger_4jets"]) == [False, False, False]

    filters = {"trigger_3jets": ["Jet:0:3:20:3PFCentralJetTightIDPt20"]}
    masks = get_trigger_object_matching_masks(events, filters, OBJECT_TYPES)
    assert list(masks["trigger_3jets"]) == [True, False, False]

    # HT filters are not matched to the offline objects
    filters = {"trigger_ht": ["HT:5:0:280:PFHT280Jet30"]}
    masks = get_trigger_object_matching_masks(events, filters, OBJECT_TYPES)
    assert list(masks["trigger_ht"]) == [True, False, True]

    # the OR of the triggers is returned
    filters = {
        "trigger_3jets": ["Jet:0:3:20:3PFCentralJetTightIDPt20"],
        "trigger_ht": ["HT:5:0:280:PFHT280Jet30"],
    }
    assert list(get_trigger_object_matching_mask(events, filters, OBJECT_TYPES)) == [
        True, False, True,
    ]
    assert list(
        get_trigger_object_matching_mask(events, filters, OBJECT_TYPES, triggers=["trigger_3jets"])
    ) == [True, False, False]

    # the AND of the filters of the same trigger is required
    filters = {
        "trigger": ["Jet:0:3:20:3PFCentralJetTightIDPt20", "HT:5:0:280:PFHT280Jet30"]
    }
    assert list(get_trigger_object_matching_mask(events, filters, OBJECT_TYPES)) == [
        True,
        False,
        False,
    ]

    # without the offline matching only the number of trigger objects is required
    filters = {"trigger_2jets": ["Jet:0:2:20:2PFCentralJetTightIDPt20"]}
    masks = get_trigger_object_matching_masks(
        events, filters, OBJECT_TYPES, match_objects=False
    )
    assert list(masks["trigger_2jets"]) == [True, True, False]

    with pytest.raises(Exception):
        get_trigger_object_matching_mask(events, filters, OBJECT_TYPES, triggers=["not_configured"])

    # an unconfigured type is a clear error, not a silent no-match
    with pytest.raises(Exception):
        get_trigger_object_matching_masks(
            events, {"t": ["Muon:0:1:20:1mu"]}, OBJECT_TYPES
        )


def test_trigger_object_matching_generic_types_and_collection_override(events):
    '''The matching is generic over the trigger object type and the offline
    collection: an Electron-type filter matches against ElectronGood (its default
    collection), and an explicit `collection` override on the filter takes
    precedence over the type's default.
    '''
    electrons = ak.zip({
        "pt": [[35.0], [], [40.0]],
        "eta": [[0.0], [], [0.0]],
        "phi": [[0.0], [], [3.0]],
    })
    ev = ak.with_field(events, electrons, "ElectronGood")
    ev = ak.with_field(ev, electrons, "MyOtherElectronCollection")

    # the electron trigger object (id 11, not present in the base fixture's TrigObj)
    # is added only to the first and third event, close to the offline electron
    trigobj = ak.zip({
        "id": [[11], [], [11]],
        "eta": [[0.05], [], [0.05]],
        "phi": [[0.05], [], [3.05]],
        "filterBits": [[1], [], [1]],
    })
    ev = ak.with_field(ev, trigobj, "TrigObj")

    filters = {"trigger_e": ["Electron:0:1:30:1e"]}
    masks = get_trigger_object_matching_masks(ev, filters, OBJECT_TYPES)
    assert list(masks["trigger_e"]) == [True, False, True]

    # an explicit `collection` override is used instead of the type's default
    filters_override = {
        "trigger_e": [
            {"type": "Electron", "bit": 0, "n_objects": 1, "threshold": 30,
             "name": "1e", "collection": "MyOtherElectronCollection"}
        ]
    }
    masks_override = get_trigger_object_matching_masks(ev, filters_override, OBJECT_TYPES)
    assert list(masks_override["trigger_e"]) == list(masks["trigger_e"])

    # a matchable type with no collection available anywhere is a clear error
    with pytest.raises(Exception):
        get_trigger_object_matching_masks(
            ev, {"t": ["Muon:0:1:20:1mu"]},
            {"Muon": {"id": 13, "matchable": True, "default_collection": None}},
        )
