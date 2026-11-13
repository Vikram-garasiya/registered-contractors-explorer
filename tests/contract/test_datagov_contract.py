"""Upstream contract tests for the BCA Registered Contractors dataset on data.gov.sg.

The app reads data.gov.sg live (no local copy), so a change upstream breaks it
immediately. These tests pin every assumption DataGovSG_IS.Contractors_Search and the
RegisteredContractors screen make, and run nightly without a deployed app (marker: contract).
"""
import os
import re
import time

import pytest
import requests

pytestmark = pytest.mark.contract

RESOURCE_ID = os.environ.get("DATAGOV_RESOURCE_ID", "d_dcda79be4aded5f9e769b8e23ff69b47")
URL = "https://data.gov.sg/api/action/datastore_search"
HEADERS = {"x-api-key": os.environ["DATAGOV_API_KEY"]} if os.environ.get("DATAGOV_API_KEY") else {}
TIMEOUT = 60

# Fields mapped by the ContractorRecord REST structure (NameInJSON) and shown or exported by the UI.
EXPECTED_FIELDS = {
    "_id", "company_name", "uen_no", "workhead", "grade", "additional_info", "expiry_date",
    "building_no", "street_name", "unit_no", "building_name", "postal_code", "tel_no",
}
# Must match the allow-list in Contractors_Search (EffectiveSort).
SORTABLE = ["company_name", "grade", "street_name", "unit_no", "postal_code"]
EXPORT_LIMIT = 5000  # GetContractorsForExport asks for this many rows in one call

EXPIRY = re.compile(r"^\d{2}/\d{2}/\d{4}$")
POSTAL = re.compile(r"^\d{6}$")
WORKHEAD = re.compile(r"^[A-Z]{2}\d{2}[A-Z]?$")  # e.g. CR06, RW02A
UEN = re.compile(r"^[0-9A-Z]{9,10}$", re.IGNORECASE)


def get(**params):
    """GET with polite pacing and backoff: anonymous data.gov.sg traffic is rate-limited (HTTP 429).
    Set DATAGOV_API_KEY (repo secret) for higher limits."""
    for attempt in range(6):
        time.sleep(0 if HEADERS else 2.5)
        r = requests.get(URL, params={"resource_id": RESOURCE_ID, **params}, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code != 429:
            return r
        time.sleep(10 * (attempt + 1))
    pytest.fail("data.gov.sg kept returning HTTP 429; set DATAGOV_API_KEY")


def fetch(**params):
    r = get(**params)
    r.raise_for_status()
    body = r.json()
    assert body["success"] is True, body
    return body["result"]


@pytest.fixture(scope="module")
def sample():
    return fetch(limit=500)


def test_fields_unchanged(sample):
    assert EXPECTED_FIELDS <= {f["id"] for f in sample["fields"]}


def test_dataset_size_plausible(sample):
    # ~24k registrations; a sudden drop means a truncated or replaced resource.
    assert sample["total"] > 10_000


def test_values_match_expected_formats(sample):
    for rec in sample["records"]:
        assert rec["company_name"].strip(), rec
        assert rec["grade"].strip(), rec
        assert EXPIRY.match(rec["expiry_date"]), rec
        assert POSTAL.match(rec["postal_code"]), rec
        assert WORKHEAD.match(rec["workhead"]), rec
        assert UEN.match(rec["uen_no"]), rec


def test_full_text_search_narrows_results(sample):
    hit = fetch(q="ENGINEERING", limit=20)
    assert 0 < hit["total"] < sample["total"]
    assert all("ENGINEERING" in " ".join(str(v) for v in r.values()).upper() for r in hit["records"])


def test_search_with_no_match_is_empty_not_an_error():
    assert fetch(q="zzqqxx nosuchcontractor", limit=5)["total"] == 0


@pytest.mark.parametrize("raw,clean", [("#03-10", "03 10"), ("PTE. LTD.", "PTE LTD"), ("A&B", "A B")])
def test_punctuation_is_rejected_upstream_so_gov_is_strips_it(raw, clean):
    # Why Contractors_Search builds CleanQuery: upstream answers punctuation in q with
    # HTTP 409 "Validation Error". If this starts passing, the sanitiser can be relaxed.
    assert get(q=raw, limit=1).status_code == 409
    fetch(q=clean, limit=1)  # the sanitised form is accepted


@pytest.mark.parametrize("field", SORTABLE)
def test_server_side_sort_on_every_sortable_column(field):
    # The database sorts with locale collation (punctuation and case ignored), so compare
    # on the same key rather than Python's code-point order.
    key = lambda v: re.sub(r"[^0-9a-z]", "", str(v).lower())
    asc = [key(r[field]) for r in fetch(limit=30, sort=f"{field} asc")["records"]]
    desc = [key(r[field]) for r in fetch(limit=30, sort=f"{field} desc")["records"]]
    assert all(a <= b for a, b in zip(asc, asc[1:])), asc
    assert all(a >= b for a, b in zip(desc, desc[1:])), desc


def test_empty_sort_parameter_is_accepted():
    # Contractors_Search always sends sort=; an empty value must mean "dataset order".
    assert fetch(limit=3, sort="")["records"]


def test_export_limit_is_served_in_one_call():
    assert len(fetch(limit=EXPORT_LIMIT, fields="_id")["records"]) == EXPORT_LIMIT


def test_paging_is_deterministic():
    a = fetch(limit=5, offset=1000, sort="_id asc")["records"]
    b = fetch(limit=5, offset=1000, sort="_id asc")["records"]
    assert [r["_id"] for r in a] == [r["_id"] for r in b]
