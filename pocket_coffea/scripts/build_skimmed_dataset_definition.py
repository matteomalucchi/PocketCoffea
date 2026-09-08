import os
from glob import glob
from coffea.util import load
from coffea.processor import accumulate
import click
from rich import print
from pocket_coffea.utils.skim import save_skimed_dataset_definition


def build_skimmed_dataset_definition(inputfiles, pattern, outputfile, check_initial_events, skip_initial_events_check_datasets):
    '''Rebuild skimmed_dataset_definition.json from the per-chunk *.coffea outputs of a skimming run.

    Useful when the skimming job(s) completed (or were interrupted after writing their
    per-dataset/per-group *.coffea outputs) but the run crashed or was killed before
    reaching the final `save_skimed_dataset_definition` call, so `skimmed_dataset_definition.json`
    was never written.
    '''
    if inputfiles:
        files = list(inputfiles)
    else:
        files = sorted(glob(pattern))

    if not files:
        print(f"[red]No input files found (pattern: '{pattern}').[/]")
        raise SystemExit(1)

    print(f"[blue]Found {len(files)} chunk file(s):[/]")
    print(files)

    outs = [load(f) for f in files]
    total = accumulate(outs)

    datasets = list(total["skimmed_files"].keys())
    print(f"[blue]Datasets found ({len(datasets)}):[/] {datasets}")

    save_skimed_dataset_definition(
        total,
        outputfile,
        check_initial_events=check_initial_events,
        skip_initial_events_check_datasets=list(skip_initial_events_check_datasets),
    )
    print(f"[green]Skimmed dataset definition saved to {outputfile}[/]")


@click.command()
@click.argument(
    'inputfiles',
    required=False,
    type=str,
    nargs=-1,
)
@click.option(
    "-p",
    "--pattern",
    required=False,
    default="output_*.coffea",
    type=str,
    help="Glob pattern used to find the chunk output files, if no INPUTFILES are given explicitly. Default: 'output_*.coffea'",
)
@click.option(
    "-o",
    "--outputfile",
    required=False,
    default="skimmed_dataset_definition.json",
    type=str,
    help="Output json file. Default: 'skimmed_dataset_definition.json'",
)
@click.option(
    "--check-initial-events/--no-check-initial-events",
    "check_initial_events",
    default=True,
    help="Check that the number of initial events in the dataset metadata matches the cutflow (raises if not). Default: enabled",
)
@click.option(
    "--skip-initial-events-check",
    "skip_initial_events_check_datasets",
    multiple=True,
    help="Dataset name(s) for which a mismatch between the initial events in the "
         "metadata and the cutflow is tolerated (warning instead of error). Useful "
         "when a corrupted input file had to be skipped. Repeatable.",
)
def main(inputfiles, pattern, outputfile, check_initial_events, skip_initial_events_check_datasets):
    '''Rebuild skimmed_dataset_definition.json from the per-chunk *.coffea outputs of a skimming run.

    By default, it looks for files matching 'output_*.coffea' in the current directory.
    Pass explicit INPUTFILES to override, e.g.:

        build-skimmed-dataset-definition /path/to/output/output_*.coffea -o /path/to/output/skimmed_dataset_definition.json
    '''
    build_skimmed_dataset_definition(inputfiles, pattern, outputfile, check_initial_events, skip_initial_events_check_datasets)


if __name__ == "__main__":
    main()
