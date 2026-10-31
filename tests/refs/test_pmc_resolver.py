"""PubMed Central, through the routes NCBI allows programs to use.

Its OA web service was retired in August 2026, and the PDF links on its
website now answer scripts with a proof-of-work page. Programs are to use the
PMC Cloud Service: an anonymous S3 bucket, found from a DOI by the ID
converter (https://pmc.ncbi.nlm.nih.gov/tools/developers/).
"""

import pymupdf

from sextant.refs.http import FakeFetcher
from sextant.refs.models import BibEntry
from sextant.refs.resolvers.pmc import PmcResolver, idconv_url, listing_url, metadata_url

DOI = "10.5555/test.2007.0005"
TITLE = "Measuring Genome Size Variation Using a Comparative Phylogenetic Approach"
ENTRY = BibEntry(key="k", entry_type="article", title=TITLE, doi=DOI)
PDF_URL = "https://pmc-oa-opendata.s3.amazonaws.com/PMC9000001.1/PMC9000001.1.pdf"


def _pdf(title):
    doc = pymupdf.open()
    page = doc.new_page()
    for i, line in enumerate(["Open Biology Letters", title, "A. Author"]):
        page.insert_text((72, 80 + 14 * i), line, fontsize=10)
    return doc.tobytes()


def _listing(*versions):
    prefixes = "".join(f"<CommonPrefixes><Prefix>PMC9000001.{v}/</Prefix></CommonPrefixes>"
                       for v in versions)
    return ('<?xml version="1.0" encoding="UTF-8"?><ListBucketResult '
            f'xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{prefixes}</ListBucketResult>')


def _meta(version, pdf=True, manuscript=False):
    return {"pmcid": "PMC9000001", "version": version, "doi": DOI, "title": TITLE,
            "is_manuscript": manuscript, "is_retracted": False,
            "pdf_url": (f"s3://pmc-oa-opendata/PMC9000001.{version}/PMC9000001.{version}.pdf"
                        "?md5=e770c95bced82578e4eed8445c2c4120") if pdf else None}


def _fetcher(meta_by_version, pdf_bytes=None):
    return FakeFetcher(
        json_by_url={idconv_url(DOI, ""): {"status": "ok", "records": [
                         {"doi": DOI, "pmcid": "PMC9000001"}]},
                     **{metadata_url("PMC9000001", v): m for v, m in meta_by_version.items()}},
        text_by_url={listing_url("PMC9000001"): _listing(*meta_by_version)},
        bytes_by_url={PDF_URL: pdf_bytes or _pdf(TITLE)})


def test_a_pmc_copy_is_fetched_from_the_cloud_service(tmp_path):
    result = PmcResolver(contact="").resolve(ENTRY, _fetcher({1: _meta(1)}), tmp_path)

    assert result.status == "resolved", result.reason
    assert "pmc.ncbi.nlm.nih.gov/articles" not in " ".join(result.landing_pages)


def test_an_author_manuscript_is_called_one(tmp_path):
    result = PmcResolver(contact="").resolve(
        ENTRY, _fetcher({1: _meta(1, manuscript=True)}), tmp_path)

    assert "accepted manuscript" in result.reason


def test_a_version_without_a_pdf_is_passed_over(tmp_path):
    """A PDF is included only "when permissible by the publishers' licenses"."""
    result = PmcResolver(contact="").resolve(ENTRY, _fetcher({1: _meta(1, pdf=False)}), tmp_path)

    assert result.status != "resolved"


def test_an_article_not_in_pmc_costs_one_request(tmp_path):
    fetcher = FakeFetcher(json_by_url={idconv_url(DOI, ""): {"status": "ok", "records": [
        {"doi": DOI, "requested-id": DOI, "errmsg": "Identifier not found in PMC"}]}})

    result = PmcResolver(contact="").resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "unresolved"
    assert fetcher.calls == [idconv_url(DOI, "")]


def test_an_embargoed_article_is_not_looked_for(tmp_path):
    fetcher = FakeFetcher(json_by_url={idconv_url(DOI, ""): {"status": "ok", "records": [
        {"doi": DOI, "pmcid": "PMC9000001", "live": "false", "release-date": "2027-03-01"}]}})

    result = PmcResolver(contact="").resolve(ENTRY, fetcher, tmp_path)

    assert result.status == "unresolved" and "2027-03-01" in result.reason
    assert len(fetcher.calls) == 1


def test_no_email_is_sent_unless_the_reader_set_one():
    assert "email" not in idconv_url(DOI, "")
    assert "email=me%40example.org" in idconv_url(DOI, "me@example.org")


def test_a_pmc_article_with_another_title_is_not_filed(tmp_path):
    """The DOI in the .bib can name another paper; PMC's own metadata says so."""
    other = {**_meta(1), "title": "Population Genetics of Bacterial Pathogens in Soil"}

    result = PmcResolver(contact="").resolve(ENTRY, _fetcher({1: other}, _pdf(TITLE)), tmp_path)

    assert result.status != "resolved"
    assert "different" in result.reason
