# Forward jet mitigation

The calibration of the jets reconstructed at large pseudorapidity degrades over the
course of Run 3, and CMS JERC recommends dedicated mitigations for the affected
periods. PocketCoffea implements three of them behind a single set of parameters,
`forward_jet_mitigation`, **all disabled by default**: an analysis that ignores this
page keeps exactly the behaviour it had before.

## The two effects

**Forward endcap, `2.5 < |eta| < 3.0`.** The jet energy response in the forward endcap
drops with the accumulated radiation dose, and the drop grows over time within a
period. Low-pT jets reconstructed there are not described by the corrections, so they
are best removed from the analysis altogether.

**Hadron forward, `3.0 < |eta| < 5.0`.** The HF region is undercorrected in 2022-2023
because of radiation damage, an effect visible as a slope of the relative jet response
versus `|eta|` in the data/MC ratio. HF corrections derived in Z to ee events were
deployed only from the 2024 Era E data taking onwards. For the earlier periods both
the L2L3Residual correction and the JER scale factors derived in that region can be
unreliable, and an analysis may prefer to drop them rather than apply them.

## Parameters

The mitigations live in
[`pocket_coffea/parameters/forward_jet_mitigation.yaml`](https://github.com/PocketCoffea/PocketCoffea/blob/main/pocket_coffea/parameters/forward_jet_mitigation.yaml),
which is part of the default parameter set, so it is already loaded by
`get_default_parameters()`. Three blocks are available, sharing the same keys:

| Block | Applied by | Effect |
| --- | --- | --- |
| `jet_veto` | `jet_selection` | Rejects jets with `pt < pt_min` inside the window |
| `skip_jer` | `JetsCalibrator` | Leaves the jets inside the window unsmeared (MC) |
| `skip_residual` | `JetsCalibrator` | Undoes the L2L3Residual correction inside the window (data) |

| Key | Meaning |
| --- | --- |
| `enabled` | Master switch of the block, `false` in the shipped defaults |
| `eta_min`, `eta_max` | The half-open `|eta|` window `[eta_min, eta_max)` the block acts on |
| `by_year` | Per data-taking period overrides of any key above, `enabled` included |

Because `by_year` can override `enabled`, a mitigation can be turned on for a subset of
the periods only, each with its own window. This is the intended way to express the
year dependence of the JER and residual mitigations, which only concern the periods
taken before the HF corrections were deployed:

```yaml
forward_jet_mitigation:
  # veto the soft forward-endcap jets in every period
  jet_veto:
    enabled: true

  # drop the HF residuals in 2022 and 2023 only
  skip_residual:
    eta_min: 3.0
    by_year:
      2022_preEE: {enabled: true}
      2022_postEE: {enabled: true}
      2023_preBPix: {enabled: true}
      2023_postBPix: {enabled: true}

  # drop the JER smearing over the whole forward region, 2022 only
  skip_jer:
    eta_min: 2.5
    by_year:
      2022_preEE: {enabled: true}
      2022_postEE: {enabled: true}
```

Save the snippet in your analysis parameters and merge it as usual:

```python
parameters = defaults.merge_parameters_from_files(
    defaults.get_default_parameters(),
    f"{localdir}/params/forward_jet_mitigation.yaml",
    update=True,
)
```

:::{warning}
The windows and the periods above are only an example of the syntax. Take the values
that apply to your analysis from the current
[JERC recommendations](https://cms-jerc.web.cern.ch/Recommendations/).
:::

## The object-level veto

`jet_selection` combines the veto with the rest of the `object_preselection` cuts, so
enabling `jet_veto` in the parameters is enough for every workflow that calls it:

```python
self.events["JetGood"], self.jetGoodMask = jet_selection(
    self.events, "Jet", self.params, self._year, leptons_collection="LeptonGood"
)
```

The `forward_jet_veto` argument overrides the parameters for a single call, which is
useful when only some of the jet collections of an analysis should be vetoed:

```python
# force the veto on for the VBF jets, regardless of the parameters
jet_selection(self.events, "Jet", self.params, self._year, forward_jet_veto=True)
# and off for the b-jet candidates
jet_selection(self.events, "Jet", self.params, self._year, forward_jet_veto=False)
```

`forward_jet_veto=True` raises a `ValueError` if the `jet_veto` block is missing from
the parameters, so a stripped-down parameter set fails loudly instead of silently
selecting nothing.

The mask is also exposed on its own, for analyses that build their jet collections
outside `jet_selection` or that cut on an alternative pT such as a regressed one:

```python
from pocket_coffea.lib.jets import forward_jet_veto_mask

mask = forward_jet_veto_mask(
    events.Jet, self.params, self._year, pt=events.Jet.pt_regressed
)
```

The mask is `True` (a plain scalar) when the veto is inactive, so it can always be
combined with `&`.

## The calibration-level mitigations

Both are applied by `JetsCalibrator` inside `jet_correction_corrlib`, on the jets of
the configured window only. Neither needs a change in the workflow: the calibrator
already passes the parameters down, so enabling the block is all that is required.

**`skip_jer`** replaces the JER smearing factor by 1 inside the window. The `JER`
variations of those jets are dropped along with the nominal smearing, so the up and
down shifts agree with the nominal and the jets stay at their JES-corrected pT. It
only concerns MC, where the smearing is applied in the first place.

**`skip_residual`** divides the L2L3Residual factor out of the total JES factor inside
the window. It only concerns data, since MC carries no residuals, and it is skipped
unless the configured correction `level` includes the residuals. The compound
`L1L2L3Res` correction applies the residual last, on the pT after L1L2L3, so the
standalone `<jec_tag>_L2L3Residual_<jet_type>` correction is evaluated with a
fixed-point iteration to recover that pT. Two iterations are enough because the
residual depends only weakly on pT. If the JERC file of the period does not expose the
standalone residual, the calibrator raises an exception naming the missing correction
rather than applying a wrong calibration.

:::{note}
The mitigations act on the jet collections calibrated by `JetsCalibrator`. The softdrop
mass correction of `JetsSoftdropMassCalibrator` uses the AK4 corrections of the
subjets, which are central, and is left untouched.
:::

## Tests

`tests/test_forward_jet_mitigation.py` covers the parameter resolution, the veto mask,
its integration in `jet_selection` and the two calibration-level mitigations. It runs
fully offline, with no access to CVMFS or EOS needed.
