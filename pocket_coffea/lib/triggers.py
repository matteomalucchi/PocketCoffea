import logging
import numpy as np
import awkward as ak

from .trigger_sf import delta_r_table

# Track trigger names already reported as missing so the warning is not emitted
# once per chunk (this module is imported once per worker process).
_missing_trigger_warned = set()


def remove_trigger_prefix(name, prefix):
    '''Remove `prefix` from the start of a trigger `name`.

    This is a genuine prefix removal: `str.lstrip(prefix)` must NOT be used because
    it strips any leading character contained in `prefix` (a character set), which
    silently mangles trigger names, e.g. ``"HLT_TkMu50".lstrip("HLT_")`` -> ``"kMu50"``.
    '''
    return name[len(prefix):] if name.startswith(prefix) else name


def apply_trigger_mask(events, triggers_to_apply, year, invert=False, trigger_type="HLT"):
    '''Computes the HLT/L1 trigger mask doing the OR of all the triggers in the list
    '''
    trigger_mask = np.zeros(len(events), dtype="bool")
    assert trigger_type in ["HLT", "L1"], "trigger_type must be HLT or L1"
    events_trigger= getattr(events, trigger_type)

    for trigger in triggers_to_apply:
        # Special treatment for Ele32 in 2017
        if year == "2017" and (
            (trigger == 'Ele32_WPTight_Gsf_L1DoubleEG')
            & ('Ele32_WPTight' not in events_trigger.fields)
        ):
            flag = (
                ak.sum(
                    (events.TrigObj.id == 11)
                    & ((events.TrigObj.filterBits & 1024) == 1024),
                    axis=1,
                )
                > 0
            )
            trigger_mask = trigger_mask | (events_trigger[trigger] & flag)
        else:
            if trigger in events_trigger.fields:
                trigger_mask = trigger_mask | events_trigger[trigger]
            else:
                # A requested trigger is not present in this NanoAOD file. This can be
                # legitimate (trigger menu evolution across eras / NanoAOD versions) but
                # is also how a mistyped or mangled trigger name would silently vanish
                # from the OR, so surface it loudly (once per name per worker).
                key = (trigger_type, year, trigger)
                if key not in _missing_trigger_warned:
                    _missing_trigger_warned.add(key)
                    logging.warning(
                        f"[triggers] {trigger_type} path '{trigger}' (year {year}) not found "
                        f"in events.{trigger_type} fields; it is skipped in the trigger OR. "
                        f"Check the trigger name if this is unexpected."
                    )

    if invert:
        trigger_mask = ~trigger_mask
    return trigger_mask


def get_trigger_mask_byprimarydataset(events, trigger_dict, year, isMC, primaryDatasets=None, invert=False, trigger_prefix="HLT_"):
    '''Computes the HLT/L1 trigger mask

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
    :param trigger_prefix: Prefix of the triggers in the events, can be HLT_ or L1_
    :returns: the events mask.
    '''
    cfg = trigger_dict[year]
    # If is MC
    triggers_to_apply = []
    if primaryDatasets:
        # if primary dataset is passed, take all the requested trigger
        for pd in primaryDatasets:
            triggers_to_apply += [remove_trigger_prefix(t, trigger_prefix) for t in cfg[pd]]
    else:
        if isMC:
            # If MC take the OR of all primary datasets
            for pd, trgs in cfg.items():
                triggers_to_apply += [remove_trigger_prefix(t, trigger_prefix) for t in trgs]
        else:
            # If Data take only the specific pd
            triggers_to_apply += [remove_trigger_prefix(t, trigger_prefix) for t in cfg[events.metadata["primaryDataset"]]]

    # trigger_prefix is "HLT_" or "L1_"; stripping the single trailing "_" is unambiguous.
    return apply_trigger_mask(events, triggers_to_apply, year, invert=invert, trigger_type=trigger_prefix.rstrip("_"))


def _parse_trigger_filter(entry):
    '''Normalize one filter entry of `trigger_object_filters` to a plain dict.

    `entry` is either the compact string `"type:bit:n_objects:threshold:name"`
    (optionally with a 6th `:collection` field), or a mapping with the same keys
    (`type`, `bit`, `n_objects`, `threshold`, `name`, and the optional `collection`).
    The mapping form is only needed when `name` or `collection` must contain a
    colon, which the compact string cannot represent.

    :returns: dict with keys `type`, `bit` (int), `n_objects` (int), `name`, and
              `collection` (`None` if not given)
    '''
    if isinstance(entry, str):
        fields = entry.split(":")
        if len(fields) < 5:
            raise ValueError(
                f"Invalid trigger filter `{entry}`: expected at least the 5 fields "
                f"`type:bit:n_objects:threshold:name`, optionally followed by `:collection`."
            )
        return {
            "type": fields[0],
            "bit": int(fields[1]),
            "n_objects": int(fields[2]),
            "name": fields[4],
            "collection": fields[5] if len(fields) > 5 else None,
        }
    return {
        "type": entry["type"],
        "bit": int(entry["bit"]),
        "n_objects": int(entry["n_objects"]),
        "name": entry["name"],
        "collection": entry.get("collection"),
    }


def get_trigger_object_matching_masks(
    events,
    trigger_filters,
    object_types,
    dr_max=0.5,
    match_objects=True,
    require_object_id=True,
):
    '''Trigger object matching of the offline objects to the trigger objects.

    The efficiencies used to build the trigger scale factors are derived for each
    trigger filter separately: the events are therefore required to have the
    offline objects matched to the trigger objects firing each of the filters.

    This function is generic over the type of trigger object and the offline
    collection matched to it: both are configured per filter (see
    `_parse_trigger_filter` for the format of an entry of `trigger_filters`) rather
    than assumed. The `type` of each filter (e.g. `Jet`, `Electron`, `HT`, any key
    of `object_types`) resolves, via `object_types`, to the numeric `TrigObj.id` to
    require, whether this type of trigger object is matched to an offline collection
    at all, and which collection to use unless the filter overrides it (see
    `parameters/trigger_object_types.yaml`).

    Trigger object types that are not per-object, event-level quantities (`HT`,
    `MHT`, `MET` by default) are never matched to offline objects: firing the
    filter is by itself the requirement, regardless of the filter's `n_objects`.

    N.B: the meaning of the bits of `TrigObj_filterBits` is **not** consistent
    between NanoAOD versions (nor generally across eras using the same version):
    always check the NanoAOD documentation (https://cms-xpog.docs.cern.ch/autoDoc/)
    of the version used in the analysis, and configure `trigger_filters` (see
    `parameters/trigger_object_filters.yaml`) separately per NanoAOD version.

    :param events: awkward array of events
    :param trigger_filters: dictionary {trigger: [list of filters]}, for a single
                            NanoAOD version (see `parameters/trigger_object_filters.yaml`
                            and `pocket_coffea.utils.utils.get_nano_version`)
    :param object_types: dictionary {type name: {id, matchable, default_collection}}
                        (see `parameters/trigger_object_types.yaml`)
    :param dr_max: maximum deltaR between the trigger object and the offline object
    :param match_objects: if False the offline matching is skipped and only the
                          number of trigger objects passing the filter is required
    :param require_object_id: require the id of the trigger object to be equal to
                              the id of the filter's type. The `TrigObj_filterBits`
                              are defined separately for each object type, therefore
                              the id has to be checked to interpret the bits correctly.
    :returns: dictionary {trigger: mask} of the events passing the matching of all
              the filters of each trigger
    '''
    masks = {}

    for trigger, filters in trigger_filters.items():
        mask = np.ones(len(events), dtype=bool)

        for trigger_filter in filters:
            parsed = _parse_trigger_filter(trigger_filter)
            if parsed["type"] not in object_types:
                raise ValueError(
                    f"Trigger object type `{parsed['type']}` (filter `{parsed['name']}` "
                    f"of trigger `{trigger}`) is not configured in `trigger_object_types`. "
                    f"Available types: {list(object_types.keys())}."
                )
            type_cfg = object_types[parsed["type"]]

            trigobj = events.TrigObj
            passed_bit = ((trigobj.filterBits >> parsed["bit"]) & 1) == 1
            if require_object_id:
                passed_bit = passed_bit & (trigobj.id == type_cfg["id"])
            trigobj = trigobj[passed_bit]

            if not type_cfg["matchable"]:
                # Global, event-level quantities (e.g. HT, MHT, MET): no matching to
                # offline objects, a single trigger object passing the filter suffices.
                n_matched = ak.num(trigobj, axis=1)
                min_objects = 1
            elif match_objects:
                collection = parsed["collection"] or type_cfg["default_collection"]
                if collection is None:
                    raise ValueError(
                        f"Filter `{parsed['name']}` of trigger `{trigger}` has matchable "
                        f"type `{parsed['type']}` but no `collection` and no "
                        f"`default_collection` configured for it."
                    )
                deltaR = delta_r_table(trigobj, events[collection])
                n_matched = ak.sum(ak.any(deltaR < dr_max, axis=-1), axis=-1)
                min_objects = parsed["n_objects"]
            else:
                n_matched = ak.num(trigobj, axis=1)
                min_objects = parsed["n_objects"]

            mask = mask & ak.to_numpy(n_matched >= min_objects)

        masks[trigger] = mask

    return masks


def get_trigger_object_matching_mask(events, trigger_filters, object_types, triggers=None, **kwargs):
    '''OR of the trigger object matching masks of the requested triggers.

    :param events: awkward array of events
    :param trigger_filters: dictionary {trigger: [list of filters]}, for a single
                            NanoAOD version (see `get_trigger_object_matching_masks`)
    :param object_types: dictionary {type name: {id, matchable, default_collection}}
                        (see `parameters/trigger_object_types.yaml`)
    :param triggers: (optional) list of triggers to consider. If None all the
                     triggers in `trigger_filters` are used.
    :returns: mask of the events matching the trigger objects of at least one trigger

    The other arguments are passed to `get_trigger_object_matching_masks`.
    '''
    masks = get_trigger_object_matching_masks(events, trigger_filters, object_types, **kwargs)
    if triggers is not None:
        missing = [trigger for trigger in triggers if trigger not in masks]
        if len(missing) > 0:
            raise Exception(f"Trigger object filters not configured for {missing}")
        masks = {trigger: masks[trigger] for trigger in triggers}

    out = np.zeros(len(events), dtype=bool)
    for mask in masks.values():
        out = out | mask
    return out
