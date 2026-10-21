'''
Application of trigger scale factors derived per single trigger filter.

The efficiency of a trigger path is often measured by factorizing it in the
efficiency of each of the filters composing the path (plus the efficiency of the
logical OR of the L1 seeds), each of them measured as a function of a different,
analysis-specific observable (e.g., for a jet trigger, the leading jet pt, the HT,
the b-tagging score...).

The total efficiency is the product of the per-filter efficiencies and therefore
the total scale factor is the product of the per-filter data/MC efficiency ratios::

    SF = prod_i eff_data_i(x_i) / prod_i eff_MC_i(x_i) = prod_i SF_i(x_i)

where `x_i` is the observable used to measure the efficiency of the i-th filter.

The per-filter scale factors are read from a correctionlib file with the following
convention (see the `Trigger scale factors` recipe in the documentation for the
script converting the ROOT files with the efficiency curves to correctionlib):

- one correction for each filter, taking as input a `systematic` string
  (`nominal`, `up`, `down`) and the value of the observable;
- the `up` and `down` variations of the total scale factor are the product of the
  `up`/`down` variations of the single filters, which are therefore treated as
  fully correlated.

This module only provides the generic application machinery (the `trigger_sf_variables`
registry and the `sf_trigger` weight): it ships no observable of its own. The
observables are specific to each measured set of trigger scale factors, and are
registered by the analysis configuration with the `register_trigger_sf_variable`
decorator (see the `Trigger scale factors` recipe in the documentation).
'''

import awkward as ak
import numpy as np
import correctionlib

from .deltaR_matching import delta_phi

# Dictionary of the functions computing the observables used to evaluate the
# per-filter efficiencies. New observables can be added by the user with the
# `register_trigger_sf_variable` decorator.
trigger_sf_variables = {}


def register_trigger_sf_variable(name):
    '''Decorator registering a function computing an observable for the trigger SF.

    The function must have the signature `f(events, cfg)`, where `cfg` is the
    configuration dictionary of the observable, and must return a flat array with
    one entry per event.
    '''

    def decorator(function):
        if name in trigger_sf_variables:
            raise ValueError(
                f"The trigger scale factor variable `{name}` has been already registered"
            )
        trigger_sf_variables[name] = function
        return function

    return decorator


def get_trigger_sf_variable(events, cfg):
    '''Compute the observable defined by the configuration `cfg`.

    :param events: awkward array of events
    :param cfg: configuration of the observable. The `name` key selects the
                function registered in `trigger_sf_variables`, the other keys are
                passed to the function as options.
    :returns: numpy array with one entry per event
    '''
    name = cfg["name"]
    if name not in trigger_sf_variables:
        raise ValueError(
            f"Trigger scale factor variable `{name}` not available. "
            f"Available variables: {list(trigger_sf_variables.keys())}"
        )
    out = trigger_sf_variables[name](events, cfg)
    return np.ascontiguousarray(ak.to_numpy(out), dtype=np.float64)


def delta_r_table(obj, other):
    '''DeltaR between all the pairs of objects of two jagged collections.

    :returns: array with dimension (n_events, n_obj, n_other)
    '''
    first, second = ak.unzip(ak.cartesian([obj, other], axis=1, nested=True))
    return np.sqrt(
        (first.eta - second.eta) ** 2 + delta_phi(first.phi, second.phi) ** 2
    )


#############################################################################
# Trigger scale factor evaluation


def get_trigger_sf_config(params, year):
    '''Get the trigger scale factors configuration for the requested year'''
    if "trigger_scale_factors" not in params:
        raise Exception(
            "The `trigger_scale_factors` parameters are missing: they are needed "
            "to apply the `sf_trigger` weight."
        )
    cfg = params["trigger_scale_factors"]
    if year not in cfg:
        raise Exception(
            f"The trigger scale factors are not configured for the year `{year}`. "
            f"Configured years: {[k for k in cfg.keys()]}"
        )
    return cfg[year]


def load_trigger_sf_correctionset(params, year):
    '''Load the correctionlib file with the per-filter trigger scale factors'''
    return correctionlib.CorrectionSet.from_file(get_trigger_sf_config(params, year)["file"])


def sf_trigger(params, events, year, correction_set=None):
    '''Compute the total trigger scale factor as the product of the per-filter ones.

    The `up` and `down` variations are computed by shifting coherently all the
    filters, as prescribed by the derivation of the efficiencies.

    :param params: parameters of the analysis
    :param events: awkward array of events
    :param year: data-taking period
    :param correction_set: (optional) already loaded correctionlib CorrectionSet.
                           If None the file in the parameters is loaded.
    :returns: tuple (sf, sf_up, sf_down) of per-event scale factors
    '''
    cfg = get_trigger_sf_config(params, year)
    if correction_set is None:
        correction_set = correctionlib.CorrectionSet.from_file(cfg["file"])

    variations = ["nominal", "up", "down"]
    sf = {variation: np.ones(len(events), dtype=np.float64) for variation in variations}

    for correction in cfg["corrections"]:
        x = get_trigger_sf_variable(events, correction["variable"])
        evaluator = correction_set[correction["name"]]
        for variation in variations:
            sf[variation] = sf[variation] * evaluator.evaluate(variation, x)

    return sf["nominal"], sf["up"], sf["down"]
