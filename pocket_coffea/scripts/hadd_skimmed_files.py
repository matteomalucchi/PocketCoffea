#!/usr/bin/env python
import os
from multiprocessing import Pool
from functools import partial
import argparse
from collections import defaultdict
from coffea.util import load
import subprocess
import json
import click

def do_hadd(group, overwrite=False):
    try:
        print("Running: ", group[0])
        if overwrite:
            subprocess.run(["hadd", "-f", group[0], *group[1]], check=True)
        else:
            subprocess.run(["hadd", group[0], *group[1]], check=True)
        return group[0], 0
    except subprocess.CalledProcessError as e:
        print("Error producing group: ", group[0])
        print(e.stderr)
        return group[0], 1

@click.command()
@click.option(
    '-fl',
    '--files-list',
    required=True,
    type=str,
    help='Parquet file containing the skimmed files metadata',
)
@click.option("-o", "--outputdir", type=str, help="Output folder")
@click.option(
    "--only-datasets", 
    type=str, 
    multiple=True, 
    help="Restring list of datasets"
)
@click.option("-f", "--files", type=int, help="Limit number of files")
@click.option("-e", "--events", type=int, help="Limit number of files")
@click.option(
    "-s",
    "--scaleout",
    type=int,
    help="Number of threads to process the hadd.",
    default=2,
)
@click.option("--overwrite", is_flag=True, help="Overwrite files")
@click.option("--dry", is_flag=True, help="Do not execute hadd, save metadata")
def hadd_skimmed_files(files_list, outputdir, only_datasets, files, events, scaleout, overwrite, dry):
    '''
    Regroup skimmed datasets by joining different files (like hadd for ROOT files) 
    '''
    df = load(files_list)
    workload = []
    groups_metadata = {}
    if files is None or files > 500:
        files = 500 # to avoid max size of command args
    
    for dataset in df["skimmed_files"].keys():
        if only_datasets and dataset not in only_datasets:
            continue
        groups_metadata[dataset] = defaultdict(dict)
        nevents_tot = 0
        nfiles = 0
        group = []
        ngroup = 1
        for file, nevents in zip(
            df["skimmed_files"][dataset], df["nskimmed_events"][dataset]
        ):
            if (files and (nfiles + 1) > files) or (
                events and (nevents_tot + nevents) > events
            ):
                outfile = f"{outputdir}/{dataset}/{dataset}_{ngroup}.root"
                workload.append((outfile, group[:]))
                groups_metadata[dataset]["files"][outfile] = group[:]
                group.clear()
                ngroup += 1
                nfiles = 0
                nevents_tot = 0
            
            group.append(file)
            nfiles += 1
            nevents_tot += nevents

        # add last group
        if len(group):
            outfile = f"{outputdir}/{dataset}/{dataset}_{ngroup}.root"
            workload.append((outfile, group[:]))
            groups_metadata[dataset]["files"][outfile] = group[:]

    print(f"We will hadd {len(workload)} groups of files.")
    print("Samples:", groups_metadata.keys())

    # Create one output folder for each dataset
    for outfile, group in workload:
        basedir = os.path.dirname(outfile)
        if not os.path.exists(basedir):
            os.makedirs(basedir)

    if not dry:
        p = Pool(scaleout)
        
        results = p.map(partial(do_hadd, overwrite=overwrite), workload)

        print("\n\n\n")
        for group, r in results:
            if r != 0:
                print("#### Failed hadd: ", group)

    json.dump(groups_metadata, open("hadd.json", "w"), indent=2)
    # writing out a script with the hadd commands
    with open("hadd.sh", "w") as f:
        for output, group in workload:
            f.write(f"hadd -ff {output} {' '.join(group)}\n")
    with open("do_hadd.py", "w") as f:
        f.write(f"""import os
import sys
from multiprocessing import Pool
import subprocess

def do_hadd(cmd):
    try:
        output = subprocess.check_output(cmd, shell=True)
    except subprocess.CalledProcessError as grepexc:                                                                                                   
        print("error code", grepexc.returncode, grepexc.output)
        return cmd.split(" ")[2]
    except Exception as e:
        print("error", e)
        return cmd.split(" ")[2]

workload = []
with open("hadd.sh") as f:
    for line in f:
        workload.append(line.strip())

p = Pool({scaleout})
if len(sys.argv)> 1:
    workload = list(filter(lambda x: sys.argv[1] in x, workload))

failed = p.map(do_hadd, workload)

print("DONE!")
print("Failed files:")
for f in failed:
    if f:
        print(f)""")
    
    # Now saving the dataset definition file
    dataset_metadata = df["datasets_metadata"]["by_dataset"]
    dataset_definition = {}
    for s, d in groups_metadata.items():
        metadata = dataset_metadata[s]
        skim_efficiency = df["cutflow"]["skim"][s] / df["cutflow"]["initial"][s]
        metadata["size"] = str(int(skim_efficiency * int(df["datasets_metadata"]["by_dataset"][s]["size"]))) # Compute the (approximate) size of the skimmed dataset
        metadata["nevents"] = str(sum(df["nskimmed_events"][s]))
        metadata["skim_efficiency"] = str(skim_efficiency)
        if metadata["isMC"] in ["True", "true", True]:
            metadata["skim_rescale_genweights"] = str(df["sum_genweights"][s] / df["sum_genweights_skimmed"][s]) # Compute the rescale factor for the genweights as the inverse of the skim genweighed efficiency
        metadata["isSkim"] = "True"
        dataset_definition[s] = {"metadata": metadata, "files": list(d['files'].keys())}

    json.dump(dataset_definition, open("skimmed_dataset_definition_hadd.json", "w"), indent=2)

    print("DONE!")


if __name__ == "__main__":
    hadd_skimmed_files()
