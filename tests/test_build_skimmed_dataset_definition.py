import pytest


def test_no_files_found_exits_cleanly(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import pocket_coffea.scripts.build_skimmed_dataset_definition as bsdd

    with pytest.raises(SystemExit):
        bsdd.build_skimmed_dataset_definition(
            inputfiles=(), pattern="output_*.coffea", outputfile="skimmed_dataset_definition.json",
            check_initial_events=True, skip_initial_events_check_datasets=(),
        )


def test_accumulates_chunks_and_saves_definition(tmp_path, monkeypatch):
    import pocket_coffea.scripts.build_skimmed_dataset_definition as bsdd

    chunk_files = [str(tmp_path / f"output_{i}.coffea") for i in range(2)]
    for f in chunk_files:
        open(f, "w").close()

    fake_chunks = {
        chunk_files[0]: {"skimmed_files": {"dsA": ["a1.root"]}},
        chunk_files[1]: {"skimmed_files": {"dsA": ["a2.root"]}},
    }
    accumulated = {"skimmed_files": {"dsA": ["a1.root", "a2.root"]}}

    monkeypatch.setattr(bsdd, "load", lambda f: fake_chunks[f])
    monkeypatch.setattr(bsdd, "accumulate", lambda outs: accumulated)

    saved = {}

    def fake_save(total, outputfile, check_initial_events, skip_initial_events_check_datasets):
        saved["total"] = total
        saved["outputfile"] = outputfile
        saved["check_initial_events"] = check_initial_events
        saved["skip_initial_events_check_datasets"] = skip_initial_events_check_datasets

    monkeypatch.setattr(bsdd, "save_skimed_dataset_definition", fake_save)

    outputfile = str(tmp_path / "skimmed_dataset_definition.json")
    bsdd.build_skimmed_dataset_definition(
        inputfiles=tuple(chunk_files), pattern="output_*.coffea", outputfile=outputfile,
        check_initial_events=False, skip_initial_events_check_datasets=("dsB",),
    )

    assert saved["total"] is accumulated
    assert saved["outputfile"] == outputfile
    assert saved["check_initial_events"] is False
    assert saved["skip_initial_events_check_datasets"] == ["dsB"]


def test_glob_pattern_used_when_no_inputfiles(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import pocket_coffea.scripts.build_skimmed_dataset_definition as bsdd

    chunk_files = sorted(str(tmp_path / f"output_{i}.coffea") for i in range(3))
    for f in chunk_files:
        open(f, "w").close()

    seen = []
    monkeypatch.setattr(bsdd, "load", lambda f: seen.append(f) or {"skimmed_files": {}})
    monkeypatch.setattr(bsdd, "accumulate", lambda outs: {"skimmed_files": {}})
    monkeypatch.setattr(bsdd, "save_skimed_dataset_definition", lambda *a, **k: None)

    bsdd.build_skimmed_dataset_definition(
        inputfiles=(), pattern=str(tmp_path / "output_*.coffea"), outputfile=str(tmp_path / "out.json"),
        check_initial_events=True, skip_initial_events_check_datasets=(),
    )

    assert seen == chunk_files
