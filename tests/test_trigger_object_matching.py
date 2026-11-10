"""Offline unit tests for the generic DeltaR-based trigger object matching."""
import awkward as ak
import pytest

from pocket_coffea.lib.cut_functions import (
    get_trigger_object_matching,
    trigger_object_matching_mask,
)


def _events():
    jets = ak.zip(
        {
            "pt": [[40.0, 30.0], [50.0]],
            "eta": [[0.0, 3.0], [0.0]],
            "phi": [[0.0, 2.0], [0.0]],
        }
    )
    trigobj = ak.zip({"eta": [[0.01], []], "phi": [[0.01], []]})
    return ak.zip({"JetGood": jets, "TrigObj": trigobj}, depth_limit=1)


def test_trigger_object_matching_mask():
    events = _events()
    mask = trigger_object_matching_mask(events.JetGood, events.TrigObj, dr_max=0.5)
    # event 0: first jet is close to the trigger object, second is not
    # event 1: no trigger object at all, the only jet is unmatched
    assert [list(m) for m in mask] == [[True, False], [False]]


def test_get_trigger_object_matching_require_all_and_any():
    events = _events()
    cut_all = get_trigger_object_matching(collection="JetGood", dr_max=0.5, require="all")
    cut_any = get_trigger_object_matching(collection="JetGood", dr_max=0.5, require="any")

    assert list(cut_all.get_mask(events, processor_params={})) == [False, False]
    assert list(cut_any.get_mask(events, processor_params={})) == [True, False]


def test_get_trigger_object_matching_invalid_require():
    with pytest.raises(ValueError):
        get_trigger_object_matching(require="banana")


def test_get_trigger_object_matching_default_name():
    cut = get_trigger_object_matching(collection="JetGood", dr_max=0.5)
    assert cut.name == "trigger_object_matching_JetGood_dr0.5"
