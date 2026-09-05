import numpy as np
import awkward as ak

from .trigger_sf import delta_r_table

def apply_trigger_mask(events, triggers_to_apply, year, invert=False):
    '''Computes the HLT trigger mask doing the OR of all the triggers in the list
    '''
    trigger_mask = np.zeros(len(events), dtype="bool")

    for trigger in triggers_to_apply:
        # Special treatment for Ele32 in 2017
        if year == "2017" and (
            (trigger == 'Ele32_WPTight_Gsf_L1DoubleEG')
            & ('Ele32_WPTight' not in events.HLT.fields)
        ):
            flag = (
                ak.sum(
                    (events.TrigObj.id == 11)
                    & ((events.TrigObj.filterBits & 1024) == 1024),
                    axis=1,
                )
                > 0
            )
            trigger_mask = trigger_mask | (events.HLT[trigger] & flag)
        else:
            if trigger in events.HLT.fields:
                trigger_mask = trigger_mask | events.HLT[trigger]

    if invert:
        trigger_mask = ~trigger_mask
    return trigger_mask


def get_trigger_mask_byprimarydataset(events, trigger_dict, year, isMC, primaryDatasets=None, invert=False):
    '''Computes the HLT trigger mask

    The function reads the triggers configuration and create the mask.
    For MC the OR of all the triggers is performed.
    For DATA only the corresponding primary dataset triggers are applied.
    if primaryDataset param is passed, the correspoding triggers are applied, both
    on DATA and MC.

    :param events: Awkward arrays
    :param key: Key of the triggers config
    :param year: year of the dataset
    :param isMC: MC/data
    :param primaryDatasets: default None. Overwrite the configuration and applied the specified
                            list of primary dataset triggers both on MC and data
    :param invert: Invert the mask, returning which events do not path ANY of the triggers
    :returns: the events mask.
    '''
    cfg = trigger_dict[year]
    # If is MC
    triggers_to_apply = []
    if primaryDatasets:
        # if primary dataset is passed, take all the requested trigger
        for pd in primaryDatasets:
            triggers_to_apply += [t.lstrip("HLT_") for t in cfg[pd]]
    else:
        if isMC:
            # If MC take the OR of all primary datasets
            for pd, trgs in cfg.items():
                triggers_to_apply += [t.lstrip("HLT_") for t in trgs]
        else:
            # If Data take only the specific pd
            triggers_to_apply += [t.lstrip("HLT_") for t in cfg[events.metadata["primaryDataset"]]]

    return apply_trigger_mask(events, triggers_to_apply, year, invert=invert)


def get_trigger_object_matching_masks(
    events,
    trigger_filters,
    collection="JetGood",
    dr_max=0.5,
    match_objects=True,
    require_object_id=True,
):
    '''Trigger object matching of the offline objects to the trigger objects.

    The efficiencies used to build the trigger scale factors are derived for each
    trigger filter separately: the events are therefore required to have the
    offline objects matched to the trigger objects firing each of the filters.

    The filters are configured with a list of strings `A:B:C:D:E` for each trigger,
    following the convention of the NanoAOD `TrigObj_filterBits` documentation:

    - `A`: type of the trigger object (Jet 1, MET 2, HT 3, FatJet 6, Electron 11,
      Muon 13, Tau 15, Photon 22, boosted Tau 1515)
    - `B`: index of the bit of `TrigObj_filterBits` for the specific filter
    - `C`: number of objects required to pass the filter
    - `D`: online threshold of the filter (not used, kept for bookkeeping)
    - `E`: name of the filter

    N.B: the trigger bits are **not** consistent between NanoAOD versions, always
    check the NanoAOD documentation (https://cms-xpog.docs.cern.ch/autoDoc/) of the
    version used in the analysis.

    HT filters (type 3) are not matched to offline objects: a single trigger object
    passing the filter is required.

    :param events: awkward array of events
    :param trigger_filters: dictionary {trigger: [list of filters]} for the year
    :param collection: collection of offline objects matched to the trigger objects
    :param dr_max: maximum deltaR between the trigger object and the offline object
    :param match_objects: if False the offline matching is skipped and only the
                          number of trigger objects passing the filter is required
    :param require_object_id: require the id of the trigger object to be equal to
                              the type of the filter. The `TrigObj_filterBits` are
                              defined separately for each object type, therefore the
                              id has to be checked to interpret the bits correctly.
    :returns: dictionary {trigger: mask} of the events passing the matching of all
              the filters of each trigger
    '''
    objects = events[collection]
    masks = {}

    for trigger, filters in trigger_filters.items():
        mask = np.ones(len(events), dtype=bool)

        for trigger_filter in filters:
            obj_type, bit, min_objects = (
                int(field) for field in trigger_filter.split(":")[:3]
            )
            trigobj = events.TrigObj
            passed_bit = ((trigobj.filterBits >> bit) & 1) == 1
            if require_object_id:
                passed_bit = passed_bit & (trigobj.id == obj_type)
            trigobj = trigobj[passed_bit]

            if obj_type == 3:
                # HT filters: no matching to offline objects, a single trigger
                # object passing the filter is required
                n_matched = ak.num(trigobj, axis=1)
                min_objects = 1
            elif match_objects:
                deltaR = delta_r_table(trigobj, objects)
                n_matched = ak.sum(ak.any(deltaR < dr_max, axis=-1), axis=-1)
            else:
                n_matched = ak.num(trigobj, axis=1)

            mask = mask & ak.to_numpy(n_matched >= min_objects)

        masks[trigger] = mask

    return masks


def get_trigger_object_matching_mask(events, trigger_filters, triggers=None, **kwargs):
    '''OR of the trigger object matching masks of the requested triggers.

    :param events: awkward array of events
    :param trigger_filters: dictionary {trigger: [list of filters]} for the year
    :param triggers: (optional) list of triggers to consider. If None all the
                     triggers in `trigger_filters` are used.
    :returns: mask of the events matching the trigger objects of at least one trigger

    The other arguments are passed to `get_trigger_object_matching_masks`.
    '''
    masks = get_trigger_object_matching_masks(events, trigger_filters, **kwargs)
    if triggers is not None:
        missing = [trigger for trigger in triggers if trigger not in masks]
        if len(missing):
            raise Exception(f"Trigger object filters not configured for {missing}")
        masks = {trigger: masks[trigger] for trigger in triggers}

    out = np.zeros(len(events), dtype=bool)
    for mask in masks.values():
        out = out | mask
    return out
