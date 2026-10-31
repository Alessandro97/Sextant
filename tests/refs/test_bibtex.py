from sextant.refs.bibtex import parse_bib

SAMPLE = """
@ARTICLE{9000001,
  author={Roe, Alex and Núñez, Inés Ángela},
  journal={Journal of Alpine Field Studies},
  title={Seasonal Dynamics of Soil Microbial Communities in Alpine Meadows},
  year={2017},
  doi={10.5555/test.2017.0001}}

@inproceedings{smith24cooperative,
  author={Smith, A.},
  title={Cooperative Pollinator Foraging in Fragmented Agricultural Landscapes},
  booktitle={2024 18th International Symposium on Pollination Biology (ISPB2024-Fall)},
  year={2024},
  doi={10.5555/test.2024.0002}}

@IEEEtranBSTCTL{IEEEexample:BSTcontrol}

@misc{noTitleHere,
  author={Anon},
  year={2020}}
"""


def test_parses_every_entry_type_case_insensitively():
    entries = parse_bib(SAMPLE)
    assert set(entries) == {"9000001", "smith24cooperative", "noTitleHere"}
    assert entries["9000001"].entry_type == "article"


def test_control_entries_are_skipped():
    assert "IEEEexample:BSTcontrol" not in parse_bib(SAMPLE)


def test_title_is_not_confused_with_booktitle():
    """The trap: a naive `title\\s*=` regex matches `booktitle` too.

    Getting this wrong makes every @inproceedings entry look like a DOI
    mismatch, because the conference name is compared against the paper.
    """
    entry = parse_bib(SAMPLE)["smith24cooperative"]
    assert entry.title.startswith("Cooperative Pollinator")
    assert "Symposium on Pollination Biology" not in entry.title


def test_missing_fields_are_none():
    entry = parse_bib(SAMPLE)["noTitleHere"]
    assert entry.title is None
    assert entry.doi is None


def test_braces_are_stripped_from_values():
    """IEEE exports wrap capitalised words: title={{The Economics of X}}."""
    entries = parse_bib("@article{k, title={{The Economics of X}}, year={2020}}")
    assert entries["k"].title == "The Economics of X"


def test_malformed_entry_is_skipped_not_fatal():
    entries = parse_bib("@article{good, title={Fine}}\n@article{\n@article{also, title={Ok}}")
    assert "good" in entries and "also" in entries


def test_parses_the_real_bibliography(real_bib_text):
    entries = parse_bib(real_bib_text)
    assert len(entries) > 400
    assert all(e.entry_type == e.entry_type.lower() for e in entries.values())
