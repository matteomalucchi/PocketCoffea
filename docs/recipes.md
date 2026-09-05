# HOW-TOs for common tasks

:::{alert}
Page under construction! Come back for more common analysis steps recipes.
:::

## HLT trigger selection

## Define a new cut function


## Skimming events
Skimming NanoAOD events and save the reduced files on disk can speedup a lot the processing of the analysis. The recommended executor for the skimming process is the direct condor-job executor, which splits the workload in condor jobs without using the dask scheduler. This makes the resubmission of failed skim jobs easier. 

Follow these instructions to skim the files on EOS:
1. Add the `save_skimmed_files` argument to the configurator with a suitable folder name: e.g. `  save_skimmed_files = "root://eoscms.cern.ch//eos/cms/store/group/phys_higgs/ttHbb/Run3_semileptonic_skim/"`
    
2. It is recommended to run the processing on HTCondor at CERN using the new direct condor executor. That will send out standard jobs instead of using dask. Please make sure your dataset list is up-to-date before sending the jobs. 
   ```pocket-coffea run --cfg config_skim.py  -o output_skim_config -e condor@lxplus --scaleout NUMBEROFJOBS --chunksize 200000 --job-dir jobs --job-name skim --queue workday --dry-run``` . Use the `--dry-run` option to check the job splitting configuration and remove it when you are happy to submit the jobs.

3. Check the status of the jobs with `pocket-coffea check-jobs -j jobs-dir/skim`.  Optionally activate the automatic resubmitting option to resubmit failed jobs. 

4. Once done, we usually do an hadd to sum all the small files produced by each saved chunk. An utility script to compute the groups and correctly hadd them is available `pocket-coffea hadd-skimmed-files -fl ../output_total.coffea -o root://eoscms.cern.ch//eos/cms/store/group/phys_higgs/ttHbb/Run3_dileptonic_skim_hadd -e 400000 --dry  -s 6 `
   this script creates some files to be able to send out jobs that runs the hadd for each group of files.

5. From all this process you will get out at the end an updated `dataset_definition_file.json` to be used in your analysis config.

## Subsamples
WIP


### Primary dataset cross-cleaning
WIP


## Define a custom weight
WIP

### Define a custom weights with custom variations
WIP

## Apply corrections
Here we describe how to apply certain corrections recommended by CMS POGs.

### MET-xy
From a purely physical point of view, the distribution of the $\phi$-component of the missing transverse momentum (a.k.a. MET) should be uniform due to rotational symmetry. However, for a variety of detector-related reasons, the distribution is not uniform in practice, but shows a sinus-like behavior. To correct this behavior, the x- and y-component of the MET can be altered in accordance to the recommendation of JME. In the PocketCoffea workflow, these corrections can be applied using the `met_xy_correction()` function:

```
from pocket_coffea.lib.jets import met_xy_correction
met_pt_corr, met_phi_corr = met_xy_correction(self.params, self.events, self._year, self._era)
```  
Note, that this shift also alters the $p_\mathrm{T}$ component! Also, the corrections are only implemented for Run2 UL (thus far).

### Jet energy regression
Starting from Run3 datasetes the ParticleNet jet energy regression corrections are part of the `Jet` object in NanoAOD. But they are not applied by default. In PocketCoffea the regression can be turned On/Off via configuration in the `Jet` object of `object_preselection.yaml` as follows:

```yaml
object_preselection:
  ...
  Jet:
	pt: 20
    ...
    regression:
      do: True
      cut_btagB: 0.12
      cut_btagCvL: 0.12
```

The corrections are applied in `jet_correction()` method in `lib/jets.py`. The implementation is based on [this presentation](https://indico.cern.ch/event/1476286/contributions/6220149/subcontributions/514978/attachments/2965734/5217706/PNetRegDiscussion_MKolosova_12Nov2024.pdf) from HH4b folks.

In principle this regression was designed to be applied to all jets (heavy flavor and light flavor), but according to the JME, there are some issues with its application to light flavor jets. This is why the cuts on b/c-tagging scores are introduced above. The regression is applied to the jets that pass an **OR** of these cuts: `(j.btagPNetB>cut_btagB) | (j.btagPNetCvL>cut_btagCvL)`  

Further references:  
* The analysis note: [AN-2022/094](https://cms.cern.ch/iCMS/jsp/db_notes/noteInfo.jsp?cmsnoteid=CMS%20AN-2022/094)
* Measuring response in Z+b events: [presenation](https://indico.cern.ch/event/1451196/contributions/6181213/attachments/2949253/5183620/cooperstein_HH4b_oct162024.pdf)

### Trigger scale factors

The efficiency of a trigger path is often measured by factorizing it in the efficiency of each of the filters composing
the path (plus the efficiency of the logical OR of the L1 seeds), each of them measured as a function of a different
observable (the pt of the N-th leading jet, the HT, the b-tagging score...). The total efficiency is the product of the
per-filter efficiencies and therefore the total scale factor is the product of the per-filter data/MC efficiency ratios

$$ SF = \frac{\prod_i \epsilon^{data}_i(x_i)}{\prod_i \epsilon^{MC}_i(x_i)} = \prod_i SF_i(x_i) $$

where $x_i$ is the observable used to measure the efficiency of the *i*-th filter. The `up` and `down` variations are
obtained by shifting **coherently** all the filters by the error of the efficiency

$$ SF^{up} = \prod_i \frac{\epsilon^{data}_i(x_i) + \sigma_i}{\epsilon^{MC}_i(x_i) + \sigma_i}, \qquad
   SF^{down} = \prod_i \frac{\epsilon^{data}_i(x_i) - \sigma_i}{\epsilon^{MC}_i(x_i) - \sigma_i} $$

N.B: since the same error is added to the numerator and to the denominator, the `up` variation of the scale factor is
*not* necessarily larger than the `down` one: they are the variations of the efficiencies, not of their ratio.

The scale factors are applied with the **sf_trigger** weight, implemented in
[`pocket_coffea.lib.trigger_sf`](pocket_coffea.lib.trigger_sf).

#### 1. Convert the efficiency curves to a correctionlib file

The efficiencies are usually provided as ROOT files containing, for each filter, the efficiency curve and the 68%
confidence intervals of the fit, both for data and for simulation:

```
<Data/Simulation>__Efficiency_<filter>              # the efficiency curve (TGraphAsymmErrors or TH1)
<Data/Simulation>__Efficiency_<filter>_FitFunction  # not used
<Data/Simulation>__Efficiency_<filter>_FitResult    # not used
<Data/Simulation>__ConfidenceIntervals_<filter>     # the error of the efficiency
```

The `convert_trigger_sf_to_correctionlib.py` script
([AnalysisConfigs](https://github.com/PocketCoffea/AnalysisConfigs)) reads the curves with `uproot`, converts them to
binned histograms and writes one correctionlib correction per filter:

```bash
# list the content of the ROOT files to check the naming of the objects
python scripts/convert_trigger_sf_to_correctionlib.py -i /path/to/trigger_efficiencies --inspect

# build the correctionlib file and the parameters to apply it
python scripts/convert_trigger_sf_to_correctionlib.py \
    -i /path/to/trigger_efficiencies \
    -y 2022_postEE --era 2022F \
    -o trigger_sf_2022_postEE.json.gz \
    --dump-params params/trigger_sf_2022_postEE.yaml
```

The list of the filters of each trigger is read from the yaml file with the trigger object filters
(`--filters-file`, see the trigger object matching below) or given explicitly with `--filters`. The script assigns to
each filter the observable used to evaluate its efficiency and dumps the corresponding PocketCoffea parameters with
`--dump-params`.

Each correction takes as input the `systematic` (`nominal`, `up`, `down`) and the value of the observable, and is built
with `flow="clamp"`, so that the events outside the range of the measurement get the scale factor of the first (last)
bin. The data and MC efficiencies are stored in the same file (`eff_data_<filter>`, `eff_mc_<filter>`) for checks.

#### 2. Configure the parameters

The correctionlib file and the list of the corrections to be applied, with the observable used to evaluate each of them,
are configured in the `trigger_scale_factors` key of the parameters (this is the file dumped by the conversion script):

```yaml
trigger_scale_factors:
  "2022_postEE":
    file: /path/to/trigger_sf_2022_postEE.json.gz
    corrections:
      # efficiency of the OR of the L1 seeds, evaluated with the Calo-HT
      - name: sf_L1All
        variable:
          name: calojet_ht
          collection: Jet
      # HLT filters, evaluated with the pt of the N-th leading in pt jet
      - name: sf_4PFCentralJetTightIDPt35
        variable:
          name: jet_pt
          collection: JetGood
          index: 4
      # b-tagging filter, evaluated with the atanh of the average b-tagging score
      # of the 2 leading in b-tagging score jets
      - name: sf_BTagCentralJetPt35PFParticleNet2BTagSum0p65
        variable:
          name: atanh_btag_mean
          collection: JetGood
          field: btagPNetB
          n: 2
```

The available observables are the functions registered in `pocket_coffea.lib.trigger_sf.trigger_sf_variables`:

| Observable | Description | Options |
| --- | --- | --- |
| `jet_pt` | pt of the `index`-th leading in pt jet | `collection` (`JetGood`), `index` (1), `pad_value` (0.) |
| `alljet_ht` | scalar sum of the pt of all the jets in the acceptance | `collection` (`Jet`), `pt` (30.), `eta` (2.5) |
| `calojet_ht` | as `alljet_ht`, excluding the jets identified as muons | as `alljet_ht` plus `muon_collection` (`Muon`), `muon_iso_field` (`pfRelIso04_all`), `muon_iso` (0.15), `muon_dr` (0.4), `muEF` (0.5), `chEmEF` (0.5), `neEmEF` (0.8) |
| `atanh_btag_mean` | atanh of the average b-tagging score of the `n` leading in b-tagging score jets | `collection` (`JetGood`), `field` (`btagPNetB`), `n` (2) |

:::{tip}
The jets are always explicitly sorted by the relevant quantity, so the observables are correct also if the collection is
sorted differently by the analysis (e.g. by b-tagging score).
:::

A custom observable can be added by the user in the configuration folder with the `register_trigger_sf_variable`
decorator (remember to register the module with `cloudpickle` to make it available to the workers):

```python
from pocket_coffea.lib.trigger_sf import register_trigger_sf_variable

@register_trigger_sf_variable("my_variable")
def my_variable(events, cfg):
    # cfg contains the configuration of the observable in the parameters
    return events[cfg.get("collection", "JetGood")].pt[:, 0]
```

#### 3. Apply the weight

The `sf_trigger` weight is part of the common weights of the framework: it is enough to add it to the weights
configuration of the `Configurator`:

```python
cfg = Configurator(
    parameters=parameters,   # including the trigger_scale_factors key
    weights_classes=common_weights,
    weights={
        "common": {
            "inclusive": ["genWeight", "lumi", "XS", "sf_trigger"],
            "bycategory": {},
        },
    },
    variations={
        "weights": {
            "common": {"inclusive": ["sf_trigger"], "bycategory": {}},
        },
    },
    ...
)
```

The weight is applied only to MC and the `sf_triggerUp`/`sf_triggerDown` variations are available if `sf_trigger` is
added to the `variations` configuration.

#### 4. Trigger object matching

Since the efficiencies are derived filter-by-filter, the events are also required to have the offline objects matched to
the trigger objects firing each of the filters. The matching is implemented by the `get_trigger_object_matching` cut,
which reads the filters from the `trigger_object_filters` parameters:

```yaml
trigger_object_filters:
  "2022_postEE":
    HLT_QuadPFJet70_50_40_35_PFBTagParticleNet_2BTagSum0p65:
      # type:bit:n_objects:threshold:name
      - "1:0:4:20:4PixelOnlyPFCentralJetTightIDPt20"
      - "1:4:4:35:4PFCentralJetTightIDPt35"
      - "1:26:2:0.65:BTagCentralJetPt35PFParticleNet2BTagSum0p65"
```

where each filter is defined by the string `type:bit:n_objects:threshold:name`, following the convention of the NanoAOD
`TrigObj_filterBits` documentation:

- `type`: type of the trigger object (Jet 1, MET 2, HT 3, FatJet 6, Electron 11, Muon 13, Tau 15, Photon 22, boosted
  Tau 1515);
- `bit`: index of the bit of `TrigObj_filterBits` corresponding to the filter;
- `n_objects`: number of objects required to pass the filter;
- `threshold`: online threshold of the filter (only for bookkeeping);
- `name`: name of the filter, the same used to name the efficiency curves.

```python
from pocket_coffea.lib.cut_functions import get_trigger_object_matching

cfg = Configurator(
    preselections=[..., get_trigger_object_matching(collection="JetGood", dr_max=0.5)],
    ...
)
```

An event passes the cut if, for at least one of the triggers, all its filters are matched: for each filter, the number
of trigger objects passing the filter bit and having an offline object within `dr_max` must be at least `n_objects`.
The HT filters (type 3) are not matched to the offline objects: a single trigger object passing the filter is required.

:::{warning}
The trigger bits are **not** consistent between NanoAOD versions: always check the NanoAOD self-documentation of the
version used in the analysis at [cms-xpog](https://cms-xpog.docs.cern.ch/autoDoc/).
:::

## Create a custom executor to use `onnxruntime`

This example shows running on CERN lxplus and assumes a prior understanding of how to load and use an ML model with onnxruntime. For more examples see the executors in the ttHbb analysis [here](https://github.com/PocketCoffea/AnalysisConfigs/tree/main/configs/ttHbb/semileptonic/common/executors)

At the time of writing, `onnxruntime` is not installed in the singularity container, which means that you will need to run with a custom environment. Instructions for this are given in [Running the analysis](./running.md)

The following code is a custom executor which is meant to be filled in with details such as the path to the `model.onnx` file and options used in the `InferenceSession`.

```python
from pocket_coffea.executors.executors_lxplus import DaskExecutorFactory
from dask.distributed import WorkerPlugin, Worker, Client

class WorkerInferenceSessionPlugin(WorkerPlugin):
    def __init__(self, model_path, session_name):
        super().__init__()
        self.model_path = model_path
        self.session_name = session_name

    async def setup(self, worker: Worker):
        import onnxruntime as ort
        session = ort.InferenceSession(
            self.model_path,
            #Whatever other options you use
            providers=["CPUExecutionProvider"]
        ) 
        worker.data["model_session_"+self.session_name] = session

class OnnxExecutorFactory(DaskExecutorFactory):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def setup(self):
        super().setup()
        self.Model = "absolute/path/to/your/model.onnx"
        inference_session_plugin = WorkerInferenceSessionPlugin(self.Model, "ModelName")
        self.dask_client.register_plugin(inference_session_plugin)

    def close(self):
        self.dask_client.close()
        self.dask_cluster.close()

def get_executor_factory(executor_name, **kwargs):
    return OnnxExecutorFactory(**kwargs)
```

To use the model to process events in the `workflow.py` file, one would do something like this. See [here](https://github.com/PocketCoffea/AnalysisConfigs/blob/main/configs/ttHbb/semileptonic/sig_bkg_classifier/workflow_test_spanet.py) for another example.
```python
#import the get_worker function
from dask.distributed import get_worker

#Rest of workflow 

#Suppose you want to apply your model after preselection. You would do e.g.
def process_extra_after_presel()
    try:
        worker = get_worker()
    except ValueError:
        worker = None

    #Whatever needs to be done to prepare the inputs to the model

    if worker is None:
        #make it work running locally too
        import onnxruntime as ort
        session = ort.InferenceSession(
            self.model_path,
            #Whatever other options you use
            providers=["CPUExecutionProvider"]
        )
    else:
        session = worker.data["model_session_ModelName"]
		
    #Continue as you normally would when using an ML model with onnxruntime, e.g.
    model_output = session.run(
        #inputs and options   
    )
```
To run with the custom executor, assuming the file is called `custom_executor.py`, one replaces `--executor dask@lxplus` with `--executor-custom-setup custom_executor.py` for example:
```
pocket-coffea run --cfg myConfig.py -o outputDir -ro run_options.yaml --executor-custom-setup custom_executor.py
```

Lastly, the custom executor will print a lot of `INFO` level log messages which are suppressed when running with the built-in pocket-coffea executors. To suppress these for all executors, create a file `~/.config/dask/logging.yaml` and add the following:
```yaml
logging:
  distributed: warning
  distributed.client: warning
  distributed.worker: warning
  distributed.nanny: warning
  distributed.scheduler: warning
```
