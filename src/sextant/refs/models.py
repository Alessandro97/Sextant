"""Value types for reference acquisition. All frozen, like the rest of the core."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class BibEntry:
    """One parsed .bib entry, restricted to the fields acquisition needs."""

    key: str
    entry_type: str  # lowercased: article, inproceedings, techreport, misc...
    title: str | None = None
    doi: str | None = None
    year: str | None = None
    authors: str | None = None
    url: str | None = None
    #: The DOI was found by a title search, not given by the bibliography: a
    #: well-founded guess, and not enough to file a copy that cannot be read.
    doi_found: bool = False
    #: That DOI is a preprint's or working paper's, found because no other
    #: work has the title. Whatever is filed under it is filed as a preprint.
    doi_is_preprint: bool = False


@dataclass(frozen=True, slots=True)
class Resolution:
    """The outcome of trying to obtain one reference.

    Failure is data. Every unresolved reference carries a reason and, where
    known, landing pages a human can click. status is one of:

        resolved   a PDF is in hand
        no-pdf     the work was identified but no direct PDF exists
        unresolved the work could not be identified at all
    """

    key: str
    status: str
    reason: str = ""
    doi: str | None = None
    title: str | None = None
    pdf_path: str | None = None
    resolver: str | None = None  # which resolver produced this
    landing_pages: tuple[str, ...] = field(default_factory=tuple)
    #: A source could not be asked this time, so a later run may still find
    #: the paper. Such a key is not recorded as attempted.
    retry: bool = False
    #: The version filed: publishedVersion, acceptedVersion, submittedVersion
    #: (a preprint), or None when unknown -- a local copy, a dropped file.
    version: str | None = None
    #: The source recognised the entry for what it is -- a standard, say --
    #: and nothing later in the chain should search for it by title.
    final: bool = False
    #: The DOI found is a preprint's or working paper's (see BibEntry).
    doi_is_preprint: bool = False
    #: The DOI the entry was asked with names a different work. Sources after
    #: this one are not handed it: PMC filed that other paper by it.
    wrong_doi: bool = False
    #: "Title — url" of copies that may be the work under another title. Not
    #: filed: only a person can tell a retitled preprint from another paper.
    similar: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class LinkCheck:
    """Does the entry's DOI resolve to the work the entry describes?

    verdict is one of: match, mismatch, unresolved, no-doi, no-title.
    """

    key: str
    verdict: str
    claimed: str | None = None
    actual: str | None = None
