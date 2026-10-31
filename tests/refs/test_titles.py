from sextant.refs.titles import canonical_title, titles_match, titles_overlap


def test_joins_hyphens_rather_than_splitting_them():
    """A .bib may say Multi-Layered Non-Woven where Crossref says Multilayered
    Nonwoven. Same paper."""
    assert canonical_title("Multi-Layered Non-Woven") == canonical_title(
        "Multilayered Nonwoven"
    )


def test_ignores_case_punctuation_and_whitespace():
    assert titles_match(
        "The Economics of X: A Comprehensive Survey",
        "the economics of x   a comprehensive survey",
    )


def test_a_shortened_title_still_overlaps():
    """Crossref sometimes returns a shortened title, so checking that a DOI
    names its entry's paper allows for it."""
    assert titles_overlap(
        "Rapid Sediment Transport in Braided River Systems",
        "Rapid Sediment Transport",
    )


def test_rejects_genuinely_different_papers():
    assert not titles_match(
        "Rapid Sediment Transport in Braided River Systems",
        "Cooperative Pollinator Foraging in Fragmented Agricultural Landscapes",
    )


def test_rejects_a_conference_name_against_a_paper_title():
    """The failure mode the booktitle trap produced."""
    assert not titles_match(
        "2024 18th International Symposium on Pollination Biology (ISPB2024-Fall)",
        "Cooperative Pollinator Foraging in Fragmented Agricultural Landscapes",
    )


def test_empty_or_missing_titles_never_match():
    assert not titles_match(None, "Anything")
    assert not titles_match("", "")


def test_too_short_a_common_prefix_does_not_match():
    """Guards against 'A' matching everything."""
    assert not titles_match("A", "A Comprehensive Survey of Wetland Restoration")


def test_a_title_hyphenated_across_a_line_break_still_matches():
    """Titles read from a PDF's reference list arrive wrapped: the store holds
    "Producer-to-Consumer", the PDF yields "producer- to-consumer", and
    without closing the space they never match."""
    from_pdf = ("Farm-to-table: A first look into the region's direct producer- "
                "to-consumer food network through crowdsourced receipts")
    from_store = ("Farm-to-Table: A First Look into the Region's Direct "
                  "Producer-to-Consumer Food Network through "
                  "Crowdsourced Receipts")

    assert titles_match(from_pdf, from_store)


def test_a_word_split_across_a_line_break_is_rejoined():
    assert canonical_title("Inte- grating archives") == "integrating archives"


def test_a_dash_used_as_punctuation_is_not_glued_to_its_neighbour():
    """'Wetlands - A Survey' must not become 'wetlandsa survey'."""
    assert canonical_title("Wetlands - A Survey") == "wetlands a survey"


def test_a_curly_apostrophe_matches_a_straight_one():
    assert titles_match("The Archivist’s Guide to Digital Preservation",
                        "The Archivist's Guide to Digital Preservation")


def test_a_preprint_retitled_on_publication_is_reported_as_a_miss():
    """The preprint is "Towards Phase 3 Vaccine Trials: Design and Endpoints";
    the published version drops the "s". The same paper, and refused anyway.

    Forgiving that "s" costs nothing here, but the latitude cannot be granted
    safely in general -- see the containment test below, where one "s" is the
    whole difference between two different papers. Filing a paper under the
    wrong citation is worse than not filing it, so this is fetched by hand."""
    assert not titles_match("Toward Phase 3 Vaccine Trials: Design and Endpoints",
                            "Towards Phase 3 Vaccine Trials: Design and Endpoints")


def test_a_phase_number_is_not_a_spelling_variant():
    """One character apart as well, and a different paper. Any tolerance loose
    enough to accept "toward"/"towards" by similarity accepts this too."""
    assert not titles_match("Toward Phase 3 Vaccine Trials: Design and Endpoints",
                            "Toward Phase 2 Vaccine Trials: Design and Endpoints")


def test_a_title_contained_in_a_longer_one_must_match_word_for_word():
    """Containment exists for truncations and added subtitles. Allowing the
    plural tolerance there as well matched a genuinely different paper."""
    assert not titles_match("A Study of Urban Gardens",
                            "A Study of Urban Garden Design")


def test_a_title_found_inside_a_longer_one_is_a_different_paper():
    """A book called "Medieval Trade" must not be matched to, and filed as,
    a paper called "Venetian Glass and Medieval Trade"."""
    assert not titles_match("Medieval Trade",
                            "Venetian Glass and Medieval Trade")


def test_the_opening_words_of_a_longer_title_are_a_different_paper():
    assert not titles_match("Machine Learning for Retinal Imaging",
                            "Machine Learning for Retinal Imaging Quality Assessment")


def test_a_subtitle_added_or_dropped_is_the_same_paper():
    assert titles_match("Urban Heat Islands and Public Health",
                        "Urban Heat Islands and Public Health: A Survey")
    assert titles_match("Urban Heat Islands and Public Health: A Survey",
                        "Urban Heat Islands and Public Health")
    assert titles_match("Is the Labour Market Ready?",
                        "Is the Labour Market Ready? A Panel Study")
    assert titles_match("Guidelines for Archiving Field Survey Data",
                        "Guidelines for Archiving Field Survey Data (Revised Edition)")
    assert titles_match("Grain Storage in Humid Climates",
                        "Grain Storage in Humid Climates — An Overview")


def test_two_subtitles_on_one_main_title_are_not_assumed_the_same():
    assert not titles_match("Urban Heat Islands and Public Health: A Survey",
                            "Urban Heat Islands and Public Health: Theory and Practice")


def test_a_dash_inside_a_title_is_not_a_subtitle_boundary():
    assert not titles_match("Growth Charts for Ages 2",
                            "Growth Charts for Ages 2–4 in Rural Clinics")


def test_a_specification_republished_by_etsi_is_the_same_specification():
    """A .bib can name a 3GPP specification the way ETSI republishes it while
    the store holds 3GPP's own title."""
    assert titles_match("5G; System architecture for the 5G System (5GS), TS 23.501 (Release 16)",
                        "System Architecture for the 5G System (5GS)")


def test_the_nr_and_lte_versions_of_a_protocol_are_different_specifications():
    assert not titles_match("NR; Radio Resource Control (RRC); Protocol specification",
                            "E-UTRA; Radio Resource Control (RRC); Protocol specification")


def test_an_acronym_in_brackets_does_not_end_the_main_title():
    """Only a bracket that closes the title is a qualifier like (Revised Edition)."""
    assert not titles_match("Volatile Organic Compounds",
                            "Volatile Organic Compounds (VOCs) in Urban Air")


def test_a_short_generic_title_does_not_stand_for_a_subtitled_one():
    """A textbook called "Organic Chemistry" against "Organic Chemistry:
    Methods and Applications" is two different works. A main title this
    short says too little to drop a subtitle for."""
    assert not titles_match("Organic Chemistry", "Organic Chemistry: Methods and Applications")
    assert not titles_match("Medieval Trade",
                            "Medieval Trade: Principles and Practice")


def test_a_short_title_on_a_body_line_is_not_the_papers_title():
    from sextant.refs.titles import title_on_page

    page = "A Survey of Something Else Entirely\nMachine learning: a field that grows\n"
    assert not title_on_page("Machine Learning", page)


def test_a_two_character_main_title_stands_for_nothing():
    from sextant.refs.titles import title_on_page

    assert not titles_match("H2", "H2: The Road Ahead")
    assert not title_on_page("H2", "H2: The Road Ahead\nA. Author")


def test_overlap_compares_whole_words():
    """A DOI check that let "Design" match "Designs" passes a wrong DOI."""
    assert not titles_overlap("Seed Bank Design",
                              "Seed Bank Designs for Arid Regions")


def test_overlap_still_compares_whole_words_when_spacing_differs():
    """Spacing may differ between two copies of a title; where a word ends
    may not."""
    assert not titles_overlap("Seed Bank Design",
                              "Seed Bank-Designs for Arid Regions")
    assert not titles_overlap("Heat Treatment for Cast Iron",
                              "Heat Treatment for Cast Ironwork Railings")
    assert titles_overlap("Heat Treatment for Cast-Iron Railings",
                          "Heat Treatment for Cast Iron Railings: A Survey")
    assert titles_overlap("Low-Cost CT", "Low Cost CT"), "too short to overlap, still equal"
    assert not titles_overlap("Low-Cost CT", "Low Cost CTs")


def test_a_hyphen_written_as_a_space_is_the_same_title():
    assert titles_match("Thermal Models for Cross-Laminated Timber Panels",
                        "Thermal Models for Cross Laminated Timber Panels")


def test_markup_and_entities_say_nothing_about_which_paper():
    assert canonical_title("Trade &amp; Development") == canonical_title("Trade \\& Development")
    assert canonical_title("A <i>Drosophila</i> Gene Atlas") == "a drosophila gene atlas"
    assert canonical_title("Yield < 0 kg and > 5 kg") == "yield 0 kg and 5 kg"


def test_an_lte_specification_republished_by_etsi_is_the_same():
    assert titles_match("LTE; Evolved Universal Terrestrial Radio Access (E-UTRA); "
                        "Physical layer procedures",
                        "Evolved Universal Terrestrial Radio Access (E-UTRA); "
                        "Physical layer procedures")


def test_ligatures_and_accents_read_as_their_letters():
    """PDF text carries "ﬁ" as one character and "č" as "ˇc"; both turned a
    paper's own first page into a different title."""
    assert canonical_title("Spin response of thin ﬁlms") == "spin response of thin films"
    assert canonical_title("Floodplain Sediments of the Morava–Beˇcva Confluence") == \
        canonical_title("Floodplain Sediments of the Morava–Bečva Confluence")
    assert canonical_title("Málaga Harbour") == "malaga harbour"


def test_a_title_on_a_page_may_differ_in_spacing():
    from sextant.refs.titles import title_on_page

    page = ("Journal\nGroundwater Recharge in a Karst Aquifer: Evidence from U.S. Watersheds\n"
            "A. Author")
    assert title_on_page("Groundwater Recharge in a Karst Aquifer: Evidence from US Watersheds",
                         page)
