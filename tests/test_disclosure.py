"""Outbox checks: which task results may go back to the orchestrator, and that the rest is held."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from umcodex.disclosure import MIN_CELL, Verdict, apply, check_outbox

PHQ9_BY_COHORT = """cohort,year,n,mean_phq9,sd_phq9
Interns,2021,412,7.31,4.82
Interns,2022,388,7.05,4.61
Residents,2021,129,6.48,4.12
Residents,2022,141,6.92,4.40
"""

COEFFICIENTS = """term,estimate,std_error,t_value,p_value,ci_low,ci_high
(Intercept),3.214,0.512,6.28,3.4e-10,2.21,4.22
sleep_hours,-0.418,0.071,-5.89,4.1e-09,-0.557,-0.279
work_hours,0.052,0.009,5.78,7.9e-09,0.034,0.070
female,0.611,0.188,3.25,0.0012,0.242,0.980
"""

COEFFICIENTS_WITH_N = """term,estimate,std_error,p_value,n
(Intercept),3.214,0.512,3.4e-10,1203
sleep_hours,-0.418,0.071,4.1e-09,1203
work_hours,0.052,0.009,7.9e-09,1187
female,0.611,0.188,0.0012,1203
"""


def outbox(tmp_path: Path, files: dict[str, str | bytes], manifest: object | None) -> Path:
    out = tmp_path / "out"
    out.mkdir(parents=True)
    for rel, content in files.items():
        path = out / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8", newline="")
    if manifest is not None:
        text = manifest if isinstance(manifest, str) else json.dumps(manifest)
        (out / "manifest.json").write_text(text, encoding="utf-8")
    return out


def table(name: str = "t.csv", count_column: str | None = "n") -> dict[str, object]:
    entry: dict[str, object] = {"path": name, "kind": "aggregate_table"}
    if count_column is not None:
        entry["count_column"] = count_column
    return entry


def one(tmp_path: Path, content: str | bytes, entry: dict[str, object] | None = None) -> Verdict:
    """The verdict on a single table (or whatever entry says) in an outbox of its own."""
    entry = entry or table()
    out = outbox(tmp_path, {str(entry["path"]): content}, {"files": [entry]})
    verdicts = {v.path: v for v in check_outbox(out)}
    assert verdicts["manifest.json"].released is False
    return verdicts[str(entry["path"])]


def held(verdict: Verdict, words: str) -> None:
    assert not verdict.released, verdict
    assert words in verdict.reason, verdict.reason


# Released


def test_mean_phq9_by_cohort_and_year_is_released(tmp_path):
    verdict = one(tmp_path, PHQ9_BY_COHORT)
    assert verdict.released
    assert verdict.reason == "aggregate table, 4 rows, smallest count 129"
    assert (verdict.rows, verdict.columns) == (4, 5)


def test_a_coefficients_table_with_n_is_released(tmp_path):
    verdict = one(tmp_path, COEFFICIENTS_WITH_N)
    assert verdict.released, verdict.reason
    assert verdict.reason == "aggregate table, 4 rows, smallest count 1187"


def test_a_coefficients_table_without_n_is_held(tmp_path):
    held(one(tmp_path, COEFFICIENTS), "count column named in manifest.json isn't in the table")
    held(one(tmp_path / "b", COEFFICIENTS, table(count_column=None)), "no count_column")


def test_a_tsv_with_missing_values_and_year_months_is_released(tmp_path):
    text = "site\tmonth\tage_band\tn\tmean_steps\n"
    text += "North\t2023-01\t18-24\t31\t\n"
    text += "North\t2023-02\t25-34\t44\tNA\n"
    text += "South\t2023-01\t65+\t19\t-1.2e3\n"
    verdict = one(tmp_path, text, table("steps.tsv"))
    assert verdict.released, verdict.reason
    assert verdict.rows == 3


def test_quarters_and_scale_names_are_labels_not_codes(tmp_path):
    text = "measure,period,n,mean\nPHQ-9,2021Q1,40,6.1\nGAD-7,2021Q2,40,5.2\nSF-36,FY2022,40,51.0\n"
    assert one(tmp_path, text).released


def test_aggregate_json_is_released(tmp_path):
    summary = {
        "outcome": "phq9",
        "groups": [
            {"cohort": "Interns", "n": 412, "mean": 7.31, "imputed": False},
            {"cohort": "Residents", "n": 129, "mean": 6.48, "sd": None},
        ],
        "total": {"n": 541},
    }
    entry = {"path": "summary.json", "kind": "aggregate_json", "count_fields": ["n"]}
    verdict = one(tmp_path, json.dumps(summary), entry)
    assert verdict.released, verdict.reason
    assert verdict.reason == "aggregate JSON, 3 counts, smallest count 129"


def test_a_utf8_bom_is_fine(tmp_path):
    assert one(tmp_path, "﻿" + PHQ9_BY_COHORT).released


def test_files_in_subfolders_are_checked(tmp_path):
    out = outbox(tmp_path, {"tables/a.csv": PHQ9_BY_COHORT}, {"files": [table("tables/a.csv")]})
    assert [(v.path, v.released) for v in check_outbox(out)] == [
        ("manifest.json", False),
        ("tables/a.csv", True),
    ]


def test_min_cell_can_be_raised(tmp_path):
    held(check_outbox(outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, {"files": [table()]}), min_cell=200)[1],
         "a count below 200")  # fmt: skip


# Held: the outbox and manifest


def test_no_manifest_holds_everything(tmp_path):
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT, "notes.md": "fine"}, None)
    assert {(v.path, v.reason) for v in check_outbox(out)} == {
        ("notes.md", "no valid manifest.json"),
        ("t.csv", "no valid manifest.json"),
    }


@pytest.mark.parametrize(
    "manifest",
    [
        "{not json",
        "[]",
        {"files": "t.csv"},
        {"files": [{"kind": "aggregate_table"}]},
        {"files": ["t.csv"]},
        {"nothing": []},
    ],
)
def test_an_invalid_manifest_holds_everything(tmp_path, manifest):
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, manifest)
    held(next(v for v in check_outbox(out) if v.path == "t.csv"), "no valid manifest.json")


def test_a_manifest_that_is_a_link_is_invalid(tmp_path):
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, None)
    real = tmp_path / "elsewhere.json"
    real.write_text(json.dumps({"files": [table()]}), encoding="utf-8")
    (out / "manifest.json").symlink_to(real)
    held(next(v for v in check_outbox(out) if v.path == "t.csv"), "no valid manifest.json")


def test_an_unlisted_file_is_held(tmp_path):
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT, "extra.csv": PHQ9_BY_COHORT}, {"files": [table()]})
    verdicts = {v.path: v for v in check_outbox(out)}
    assert verdicts["t.csv"].released
    held(verdicts["extra.csv"], "not listed in manifest.json")


def test_a_file_listed_twice_is_held(tmp_path):
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, {"files": [table(), table()]})
    held(check_outbox(out)[1], "listed more than once")


@pytest.mark.parametrize("path", ["../t.csv", "/t.csv", "./t.csv", "sub/../t.csv", "sub\\t.csv", "C:t.csv"])
def test_odd_manifest_paths_release_nothing(tmp_path, path):
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT, "sub/t.csv": PHQ9_BY_COHORT}, {"files": [table(path)]})
    assert not any(v.released for v in check_outbox(out))


def test_a_manifest_entry_for_a_missing_file_releases_nothing(tmp_path):
    out = outbox(tmp_path, {}, {"files": [table("gone.csv")]})
    assert [v.path for v in check_outbox(out)] == ["manifest.json"]


def test_a_linked_file_is_held(tmp_path):
    secret = tmp_path / "participants.csv"
    secret.write_text(PHQ9_BY_COHORT, encoding="utf-8")
    out = outbox(tmp_path, {}, {"files": [table()]})
    (out / "t.csv").symlink_to(secret)
    held(check_outbox(out)[1], "it's a link")


def test_a_linked_folder_is_held_and_not_followed(tmp_path):
    elsewhere = tmp_path / "data"
    elsewhere.mkdir()
    (elsewhere / "t.csv").write_text(PHQ9_BY_COHORT, encoding="utf-8")
    out = outbox(tmp_path, {}, {"files": [table("linked/t.csv")]})
    (out / "linked").symlink_to(elsewhere)
    verdicts = check_outbox(out)
    assert [(v.path, v.released, v.reason) for v in verdicts] == [
        ("linked", False, "it's a link"),
        ("manifest.json", False, "manifest.json stays with the held files"),
    ]


def test_a_linked_outbox_holds_everything(tmp_path):
    real = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, {"files": [table()]})
    link = tmp_path / "out-link"
    link.symlink_to(real)
    held(next(v for v in check_outbox(link) if v.path == "t.csv"), "the outbox folder is a link")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no named pipes here")
def test_a_named_pipe_is_held_without_reading_it(tmp_path):
    out = outbox(tmp_path, {}, {"files": [table()]})
    os.mkfifo(out / "t.csv")
    held(check_outbox(out)[1], "not an ordinary file")


def test_a_missing_outbox_has_no_verdicts(tmp_path):
    assert check_outbox(tmp_path / "nowhere") == []


# Held: the file


def test_a_file_over_5_mb_is_held(tmp_path):
    big = PHQ9_BY_COHORT + "Interns,2023,400,7.0,4.0\n" * 230_000
    held(one(tmp_path, big), "larger than 5 MB")


def test_a_file_that_is_not_utf8_is_held(tmp_path):
    held(one(tmp_path, PHQ9_BY_COHORT.encode("utf-16")), "not UTF-8")
    held(one(tmp_path / "b", b"cohort,n\nInterns,\xe9\xff\n"), "not UTF-8")


def test_binary_content_is_held(tmp_path):
    held(one(tmp_path, "cohort,n\nInt\x00erns,40\n"), "binary content")


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("image", "image: can't be checked automatically; review it in UM-Codex"),
        ("text", "text: can't be checked automatically; review it in UM-Codex"),
        ("table", "table: can't be checked automatically"),
        ("Jane Doe 555-1234", "this kind: can't be checked automatically"),
        (None, "this kind: can't be checked automatically"),
    ],
)
def test_other_kinds_are_held(tmp_path, kind, reason):
    entry = {"path": "t.csv", "kind": kind}
    held(one(tmp_path, PHQ9_BY_COHORT, entry), reason)


def test_an_image_is_held(tmp_path):
    held(one(tmp_path, b"\x89PNG\r\n\x1a\n", {"path": "plot.png", "kind": "image"}), "image:")


def test_aggregate_kinds_need_the_right_extension(tmp_path):
    held(one(tmp_path, PHQ9_BY_COHORT, table("t.txt")), "must be a .csv or .tsv")
    entry = {"path": "s.txt", "kind": "aggregate_json", "count_fields": ["n"]}
    held(one(tmp_path / "b", '{"n": 40}', entry), "must be a .json file")


# Held: tables


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("", "it's empty"),
        ("cohort,n\n", "no data rows"),
        ("cohort,n\nInterns,40,extra\n", "rows of different widths"),
        ("cohort,n\nInterns\n", "rows of different widths"),
        ('cohort,n\n"Interns,40\n', "couldn't be read as a table"),
        ("cohort,n,n\nA,40,40\n", "two columns have the same name"),
        ("cohort,n\nA,40\nB,10\n", "a count below 11"),
        ("cohort,n\nA,40\nB,0\n", "a count below 11"),
        ("cohort,n\nA,40\nB,\n", "count column has non-integers"),
        ("cohort,n\nA,40\nB,12.0\n", "count column has non-integers"),
        ("cohort,n\nA,40\nB,-12\n", "count column has non-integers"),
        ("cohort,n\nA,40\nB,<11\n", "count column has non-integers"),
    ],
)
def test_table_shape_and_counts(tmp_path, text, reason):
    held(one(tmp_path, text), reason)


def test_more_than_10000_rows_is_held(tmp_path):
    rows = "".join(f"{i % 7},40\n" for i in range(10_001))
    held(one(tmp_path, "group,n\n" + rows), "more than 10,000 rows")
    assert one(tmp_path / "b", "group,n\n" + rows[: rows.index("\n", 0) + 1] * 10_000).released


def test_more_than_100_columns_is_held(tmp_path):
    header = ",".join(f"m{i}" for i in range(100)) + ",n\n"
    held(one(tmp_path, header + ",".join("1" for _ in range(101)) + "\n"), "more than 100 columns")


@pytest.mark.parametrize(
    "column",
    [
        "id", "participant_id", "ParticipantID", "userId", "study_ids", "pid", "MRN", "ssn",
        "name", "cohort_name", "first_name", "LastName", "e-mail", "Email", "phone_number", "tel",
        "street_address", "zip", "zip5", "ZipCode", "postcode", "dob", "birth_date", "DateOfBirth",
        "visit_date", "ip", "url", "uuid", "guid", "record", "records", "subject", "patient", "user",
        "username", "device", "imei", "mac", "license", "account", "insurance", "initials",
        "subject identifier", "studyid", "participantid", "county", "latitude", "fax", "photo",
        "fingerprint", "vin", "certificate_no", "admit_timestamp", "uniqname", "encounterid",
    ],
)  # fmt: skip
def test_identifier_like_column_names_are_held(tmp_path, column):
    verdict = one(tmp_path, f"{column},n\nA,40\n")
    held(verdict, "looks like an identifier")
    assert column[:40] in verdict.reason


@pytest.mark.parametrize(
    "column",
    ["covid_status", "valid", "lipid_panel", "thyroid", "opioid_use", "medicaid", "mid_year", "kids",
     "mean_phq9", "sd", "p_value", "cohort", "year", "sex", "age_band", "identity_score"],
)  # fmt: skip
def test_ordinary_column_names_are_fine(tmp_path, column):
    assert one(tmp_path, f"{column},n\nA,40\n").released


def test_a_long_identifier_name_is_cut_in_the_reason(tmp_path):
    name = "participant_" + "x" * 80
    verdict = one(tmp_path, f"{name},n\nA,40\n")
    held(verdict, "looks like an identifier")
    assert name not in verdict.reason
    assert name[:39] + "…" in verdict.reason


@pytest.mark.parametrize(
    ("column_name", "reason"),
    [
        ("2023-01-05", "a column name has exact dates"),
        ("jane.doe@umich.edu", "a column name has email addresses"),
        ("P1001", "a column name has codes that look like IDs"),
        ("", "a column has no name"),
    ],
)
def test_column_names_that_look_like_values_are_held_unquoted(tmp_path, column_name, reason):
    verdict = one(tmp_path, f"cohort,{column_name},n\nA,1.0,40\n")
    held(verdict, reason)
    if column_name:
        assert column_name not in verdict.reason


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("2023-01-05", "exact dates"),
        ("01/05/2023", "exact dates"),
        ("1/5/23", "exact dates"),
        ("05-Jan-2023", "exact dates"),
        ("January 5, 2023", "exact dates"),
        ("2023-01-05T14:32:00Z", "exact dates"),
        ("14:32", "exact dates"),
        ("jane.doe@umich.edu", "email addresses"),
        ("https://example.org/x", "web addresses"),
        ("www.example.org", "web addresses"),
        ("umich.edu", "web addresses"),
        ("123-45-6789", "Social Security-like numbers"),
        ("10.0.4.17", "IP addresses"),
        ("(734) 555-0199", "phone numbers"),
        ("734-555-0199", "phone numbers"),
        ("555-0199", "phone numbers"),
        ("acct 48109123", "long runs of digits"),
        ("P1001", "codes that look like IDs"),
        ("S-012ab", "codes that look like IDs"),
        ("x" * 41, "long text"),
        ("felt tired\nall week", "line breaks or control characters"),
    ],
)
def test_sensitive_looking_labels_are_held(tmp_path, value, reason):
    text = f'cohort,note,n\nA,"{value}",40\n'
    verdict = one(tmp_path, text)
    held(verdict, f"column 'note' has {reason}")
    assert value not in verdict.reason


def test_long_whole_numbers_outside_the_count_column_are_held(tmp_path):
    held(one(tmp_path, "cohort,code,n\nA,20230105,40\n"), "column 'code' has long runs of digits")
    held(one(tmp_path / "b", "cohort,code,n\nA,7345550199.0,40\n"), "long runs of digits")
    assert one(tmp_path / "c", "cohort,n\nA,12345678\n").released  # a big count is fine


def test_too_many_distinct_labels_is_held(tmp_path):
    rows = "".join(f"group {chr(65 + i // 26)}{chr(65 + i % 26)},40\n" for i in range(31))
    held(one(tmp_path, "cohort,n\n" + rows), "more than 30 different labels")
    assert one(tmp_path / "b", "cohort,n\n" + "".join(rows.splitlines(keepends=True)[:30])).released


def test_free_text_is_held(tmp_path):
    rows = "".join(f'A,"said they slept badly on night {i}",40\n' for i in range(40))
    held(one(tmp_path, "cohort,comment,n\n" + rows), "different labels")


def test_all_different_whole_numbers_look_like_ids(tmp_path):
    rows = "".join(f"{1000 + i * 7},2.5,40\n" for i in range(21))
    held(one(tmp_path, "grp,score,n\n" + rows), "column 'grp' has all-different whole numbers")
    assert one(tmp_path / "b", "grp,score,n\n" + "".join(rows.splitlines(keepends=True)[:20])).released


def test_ages_over_89_are_held(tmp_path):
    held(one(tmp_path, "age,n\n45,40\n91,12\n"), "column 'age' has ages over 89")
    assert one(tmp_path / "b", "mean_age,n\n45.2,40\n").released


# Held: aggregate JSON


def json_entry(fields: object = ("n",)) -> dict[str, object]:
    return {"path": "s.json", "kind": "aggregate_json", "count_fields": list(fields) if fields else fields}


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ('{"mean": 7.3}', "no counts, so cell sizes can't be checked"),
        ('{"n": 7}', "a count below 11"),
        ('{"n": 0}', "a count below 11"),
        ('{"n": 40.0}', "a count field has a non-integer"),
        ('{"n": "40"}', "a count field has a non-integer"),
        ('{"n": true}', "a count field has a non-integer"),
        ('{"n": 40, "n": 41}', "a key appears twice"),
        ("[1, 2]", "must be an object or a list of objects"),
        ('"text"', "must be an object or a list of objects"),
        ("[]", "must be an object or a list of objects"),
        ("{nope", "it isn't valid JSON"),
        ('{"a": {"b": {"c": {"n": 40}}}}', "nested too deeply"),
        ('{"n": 40, "participant_id": 3}', "key 'participant_id' looks like an identifier"),
        ('{"n": 40, "2023-01-05": 3}', "a key name has exact dates"),
        ('{"n": 40, "48109": {"n": 40}}', "a key is a long number"),
        ('{"n": 40, "note": "jane.doe@umich.edu"}', "values under key 'note' have email addresses"),
        ('{"n": 40, "visit": "2023-01-05"}', "values under key 'visit' have exact dates"),
        ('{"n": 40, "code": 20230105}', "long runs of digits"),
        ('{"n": 40, "oldest_age": 93}', "key 'oldest_age' has ages over 89"),
    ],
)
def test_json_rules(tmp_path, value, reason):
    held(one(tmp_path, value, json_entry()), reason)


def test_json_needs_count_fields_in_the_manifest(tmp_path):
    held(one(tmp_path, '{"n": 40}', json_entry(None)), "no count_fields")
    held(one(tmp_path / "b", '{"n": 40}', json_entry([])), "no counts")


def test_json_with_too_many_values_is_held(tmp_path):
    held(
        one(tmp_path, json.dumps({"n": 40, "x": list(range(10_000))}), json_entry()),
        "more than 10,000 values",
    )


def test_json_with_many_labels_or_groups_is_held(tmp_path):
    labels = [{"cohort": f"group {i}", "n": 40} for i in range(31)]
    held(one(tmp_path, json.dumps(labels), json_entry()), "key 'cohort' has more than 30 different labels")
    groups = {f"site {chr(65 + i // 26)}{chr(65 + i % 26)}": {"n": 40} for i in range(31)}
    held(one(tmp_path / "b", json.dumps(groups), json_entry()), "more than 30 groups")


# Reasons never quote content


SENSITIVE = ["Jane Doe", "jane.doe@umich.edu", "123-45-6789", "P1001", "2023-01-05", "734-555-0199", "48109"]


def test_no_reason_quotes_a_value(tmp_path):
    rows = (
        "cohort,note,n\n"
        'Interns,"Jane Doe",40\n'
        "Interns,jane.doe@umich.edu,40\n"
        "Residents,123-45-6789,40\n"
        "Residents,P1001,40\n"
        "Fellows,2023-01-05,40\n"
        "Fellows,734-555-0199,40\n"
        "Fellows,48109,40\n"
    )
    files: dict[str, str | bytes] = {"t.csv": rows, "unlisted.csv": rows}
    files["s.json"] = json.dumps({"n": 40, "who": "Jane Doe", "contact": "jane.doe@umich.edu"})
    files["notes.md"] = "Jane Doe, 123-45-6789, P1001"
    for i, value in enumerate(SENSITIVE):
        files[f"each{i}.csv"] = f'cohort,n\n"{value}",40\n'
    manifest = {
        "files": [table(), json_entry(), {"path": "notes.md", "kind": "text"}]
        + [table(f"each{i}.csv") for i in range(len(SENSITIVE))]
    }
    verdicts = check_outbox(outbox(tmp_path, files, manifest))
    assert len(verdicts) == len(files) + 1
    released = {v.path for v in verdicts if v.released}
    assert released == {"each0.csv", "each6.csv"}  # "Jane Doe" and 48109 are fine as labels/numbers alone
    for verdict in verdicts:
        for value in SENSITIVE + ["Jane", "Doe", "umich", "6789", "0199"]:
            assert value not in verdict.reason, (verdict, value)


# apply


def test_apply_moves_each_file_to_released_or_held(tmp_path):
    out = outbox(
        tmp_path,
        {"by_cohort.csv": PHQ9_BY_COHORT, "tables/coef.csv": COEFFICIENTS, "plot.png": b"\x89PNG"},
        {"files": [table("by_cohort.csv"), table("tables/coef.csv"), {"path": "plot.png", "kind": "image"}]},
    )
    released, kept = tmp_path / "released", tmp_path / "held"
    verdicts = apply(out, released, kept)
    assert {(v.path, v.released) for v in verdicts} == {
        ("by_cohort.csv", True),
        ("manifest.json", False),
        ("plot.png", False),
        ("tables/coef.csv", False),
    }
    assert (released / "by_cohort.csv").read_text(encoding="utf-8") == PHQ9_BY_COHORT
    assert sorted(p.relative_to(kept).as_posix() for p in kept.rglob("*") if p.is_file()) == [
        "manifest.json",
        "plot.png",
        "tables/coef.csv",
    ]
    assert [p for p in out.rglob("*") if p.is_file()] == []
    assert not (released / "manifest.json").exists()


def test_apply_moves_links_without_following_them(tmp_path):
    secret = tmp_path / "participants.csv"
    secret.write_text("secret", encoding="utf-8")
    out = outbox(tmp_path, {}, {"files": [table()]})
    (out / "t.csv").symlink_to(secret)
    apply(out, tmp_path / "released", tmp_path / "held")
    assert (tmp_path / "held" / "t.csv").is_symlink()
    assert not (tmp_path / "released" / "t.csv").exists()
    assert secret.read_text(encoding="utf-8") == "secret"


def test_apply_never_overwrites(tmp_path):
    released, kept = tmp_path / "released", tmp_path / "held"
    released.mkdir()
    (released / "t.csv").write_text("earlier", encoding="utf-8")
    kept.mkdir()
    (kept / "manifest.json").write_text("earlier", encoding="utf-8")
    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, {"files": [table()]})
    verdicts = apply(out, released, kept)
    held(next(v for v in verdicts if v.path == "t.csv"), "already released")
    assert (released / "t.csv").read_text(encoding="utf-8") == "earlier"
    assert (kept / "t.csv").read_text(encoding="utf-8") == PHQ9_BY_COHORT
    assert (kept / "manifest.json").read_text(encoding="utf-8") == "earlier"
    assert (kept / "manifest.json.1").exists()


def test_apply_holds_a_file_that_changed_after_its_check(tmp_path, monkeypatch):
    import shutil

    from umcodex import disclosure

    out = outbox(tmp_path, {"t.csv": PHQ9_BY_COHORT}, {"files": [table()]})
    real_move = shutil.move

    def move_then_change(source, target):
        moved = real_move(source, target)
        if Path(target).name == "t.csv" and "released" in Path(target).parts:
            Path(target).write_text("participant,phq9\nP1001,22\n", encoding="utf-8")
        return moved

    monkeypatch.setattr(disclosure.shutil, "move", move_then_change)
    verdicts = apply(out, tmp_path / "released", tmp_path / "held")
    held(next(v for v in verdicts if v.path == "t.csv"), "changed while it was being checked")
    assert not (tmp_path / "released" / "t.csv").exists()
    assert (tmp_path / "held" / "t.csv").exists()


def test_min_cell_default():
    assert MIN_CELL == 11
