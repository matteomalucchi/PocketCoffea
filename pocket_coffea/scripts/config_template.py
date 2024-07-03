config_template = '''# This config has been generated by the pocket_coffea CLI {{VERSION}}.
from pocket_coffea.utils.configurator import Configurator
from pocket_coffea.lib.cut_definition import Cut
from pocket_coffea.lib.cut_functions import get_nObj_min, get_HLTsel
from pocket_coffea.parameters.cuts import passthrough
from pocket_coffea.parameters.histograms import *

import workflow
from workflow import {{PROCESSOR_CLASS}}

# Register custom modules in cloudpickle to propagate them to dask workers
import cloudpickle
import custom_cut_functions
cloudpickle.register_pickle_by_value(workflow)
cloudpickle.register_pickle_by_value(custom_cut_functions)

from custom_cut_functions import *
import os
localdir = os.path.dirname(os.path.abspath(__file__))

# Loading default parameters
from pocket_coffea.parameters import defaults
default_parameters = defaults.get_default_parameters()
defaults.register_configuration_dir("config_dir", localdir+"/params")

parameters = defaults.merge_parameters_from_files(default_parameters,
                                                    f"{localdir}/params/object_preselection.yaml",
                                                    f"{localdir}/params/triggers.yaml",
                                                    f"{localdir}/params/plotting.yaml",
                                                   update=True)
cfg = Configurator(
    parameters = parameters,
    datasets = {
        "jsons": {{DATASETS_LIST}},
        "filter" : {
            "samples": {{SAMPLES_LIST}},
            "samples_exclude" : [],
            "year": {{YEARS_LIST}}
        }
    },

    workflow = {{PROCESSOR_CLASS}},

    skim = [

    ], 

    preselections = [passthrough],
    categories = {
        "baseline": [passthrough],
    },

    weights = {
        "common": {
            "inclusive": ["genWeight","lumi","XS",
                          "pileup"],
            "bycategory": {
                          }
       },
        "bycategory" : {
                       }
        
        "bysample": {
        }
    },

    variations = {
        "weights": {
            "common": {
                "inclusive": [ ],
                "bycategory" : {
                }
            },
        "bysample": {
                    }
        "bycategory": {
                    }
        },
    },

    variables = {


    },

    columns = {

    },
)
'''


worflow_template = """# This workflow has been generated by the pocket_coffea CLI {{VERSION}}.
import awkward as ak
from pocket_coffea.workflows.base import BaseProcessorABC
from pocket_coffea.utils.configurator import Configurator
from pocket_coffea.lib.objects import (
    jet_correction,
    lepton_selection,
    jet_selection,
    btagging,
)

class {{PROCESSOR_CLASS}}(BaseProcessorABC):

    def __init__(self, cfg: Configurator):
        super().__init__(cfg)

    def apply_object_preselection(self, variation):
        '''The function applies object preselections to the events.
        It needs to be defined by the user workflow.

        As an example:

        self.events["MuonGood"] = lepton_selection(
            self.events, "Muon", self.params
        )

        self.events["JetGood"], self.jetGoodMask = jet_selection(
            self.events, "Jet", self.params, "LeptonGood"
        )

        self.events["BJetGood"] = btagging(
            self.events["JetGood"], self.params.btagging.working_point[self._year], wp=self.params.object_preselection.Jet.btag.wp)

        '''
        pass


    def count_objects(self, variation):
        '''The function counts the number of objects in the events.
        It needs to be defined by the user workflow.

        As an example:
        self.events["nMuonGood"] = ak.num(self.events.MuonGood)
        '''
        pass


    def define_common_variables_before_presel(self, variation):
        '''The function defines variables before applying the preselection cuts.
        The user must define here variables that are not available in the NanoAOD and that
        are used in the preselection functions. 

        It is not strictly necessary to define this function if there are no variables to be defined.
        '''
        pass
"""

custom_cut_functions_template = """# This code has been generated by the pocket_coffea CLI {{VERSION}}.
import awkward as ak
from pocket_coffea.lib.cut_definition import Cut

def cut_function(events, params, year, sample, **kwargs):
    # Put here your selection logic
    return ak.ones_like(events.event, dtype=bool)

cut = Cut(
    name="cut_name",
    params={
        "param1": 1,
        "param2": 2,
    },
    function=cut_function,
)
"""

dataset_definition_template = """
{
   "DATASET_NAME": {
      "sample": "SAMPLE_NAME",
      "json_output": "JSON_OUTPUT",
      "files": [
         {
             "das_names": ["DAS_NAME1", "DAS_NAME2", ...],
             "xsec": 1,
             "year": "YEAR",
             "isMC": True   
         },
          {
             "das_names": ["DAS_NAME3", "DAS_NAME4", ...],
             "xsec": 1,
             "year": "YEAR2",
             "isMC": True   
         }
      ]
   },
     "DATASET_NAME_DATA": {
      "sample": "SAMPLE_NAME",
      "json_output": "JSON_OUTPUT",
      "files": [
         {
             "das_names": ["DAS_NAME1", "DAS_NAME2", ...],
             "year": "YEAR",
             "isMC": False,
             "era": "A"
         },
          {
             "das_names": ["DAS_NAME3", "DAS_NAME4", ...],
             "year": "YEAR2",
             "isMC": False,
             "era": "A"
         }
      ]
   }
}
"""


__all__ = ["config_template", "worflow_template", "custom_cut_functions_template", "dataset_definition_template"]