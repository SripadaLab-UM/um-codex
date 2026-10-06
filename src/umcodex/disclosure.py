"""Which files in a task's outbox may go back to the orchestrator.

A task hands Codex a data step; Codex writes its results to `out/` with a
`manifest.json` saying what each file is. The orchestrator (Claude) is not
approved to see study data, so only files that are plainly aggregate results
go back to it. Everything else is held for the person, who reviews it in
UM-Codex. The checks are fixed rules, no model: a held file costs a click, a
wrongly released one is a data-protection incident, so when in doubt, hold.

The rules:
- No valid manifest.json at the top of out/: everything is held.
- A file not listed, listed twice, a link (or under a linked folder), not an
  ordinary file, over 5 MB, not UTF-8, or holding NUL bytes: held.
- Only two kinds can be released; any other kind (image, text, ...) is held.
- aggregate_table (.csv, or .tsv): a header and 1 to 10,000 data rows, every
  row as wide as the header, at most 100 columns. The manifest's
  count_column must be there, every value a whole number of at least
  MIN_CELL (zero is held too).
- aggregate_json (.json): an object, or a list of objects, at most three
  containers deep and 10,000 values. Every key named in count_fields must
  hold a whole number of at least MIN_CELL, and at least one must appear.
- Column names and JSON keys that look like identifiers are held: words
  such as id, name, email, zip, dob, date, participant, patient (split on
  punctuation, case and digits), anything with "identifier", and words
  ending in "id" that aren't ordinary English (covid, valid, lipid, ...).
- Every other value is a number, missing (blank, NA, NaN, null, ...), or a
  short label: at most 40 characters, no line breaks, nothing that looks
  like a full date or a time, an email, a web or IP address, a phone or
  Social Security number, a run of 7 or more digits, or a code mixing
  letters and 3 or more digits (like P1001; 2021Q1 is fine).
- A column (or a JSON key) with more than 30 distinct labels looks like free
  text or identifiers: held. So is a numeric column whose values are all
  whole, all different, over more than 20 rows (it looks like IDs), and
  any column named for age with a value of 90 or more.

Reasons go to the orchestrator, so they never quote a value from a file:
only counts, kinds, and, when a column or key itself is refused, its name
(at most 40 characters).
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import stat
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import Any

MIN_CELL = 11

MANIFEST = "manifest.json"
AGGREGATE_KINDS = ("aggregate_table", "aggregate_json")
_TABLE_DELIMITERS = {".csv": ",", ".tsv": "\t"}
_MAX_BYTES = 5 * 1024 * 1024
_MAX_ROWS = 10_000
_MAX_LEAVES = 10_000
_MAX_COLUMNS = 100
_MAX_DEPTH = 3  # containers: the top one and two more
_MAX_LABEL = 40  # characters in a label, a column name or a key
_MAX_LABELS = 30  # distinct labels in one column or under one key
_MAX_QUOTED = 40  # characters of a refused name shown in a reason
_ID_LIKE_ROWS = 20  # all-different whole numbers over more rows than this look like IDs
_OLDEST_AGE = 89

_MISSING = {"", "na", "n/a", "nan", "null", "none", "."}
_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?|[+-]?inf(inity)?", re.IGNORECASE)
_WHOLE = re.compile(r"\d+")
_LONG_DIGITS = re.compile(r"\d{7,}")
_CONTROL = re.compile("[\\x00-\\x1f\\x7f\\u0085\\u2028\\u2029]")
_MONTH = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?"
_DATE = re.compile(
    r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}"  # 2023-01-05, 2023/01/05
    r"|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}"  # 01/05/2023, 1-5-23
    rf"|\d{{1,2}}[- ]?{_MONTH}[- ]?\d{{2,4}}"  # 05-Jan-2023, 5 January 2023
    rf"|{_MONTH} \d{{1,2}},? \d{{4}}"  # January 5, 2023
    r"|\d{1,2}:\d{2}",  # a time of day
    re.IGNORECASE,
)
_SSN = re.compile(r"\d{3}-\d{2}-\d{4}")
_PHONE = re.compile(r"(\(\d{3}\)\s*|\b\d{3}[-. ])?\b\d{3}[-. ]\d{4}\b")
_IP = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b|\b[0-9a-f]{1,4}(:[0-9a-f]{1,4}){3,}", re.IGNORECASE)
_URL = re.compile(r"://|\bwww\.|\b[a-z0-9-]+\.(com|org|edu|net|gov|io|us|info)\b", re.IGNORECASE)
_PERIOD = re.compile(r"\d{4}[QqHhSs]\d|[QqHh]\d\d{4}|[Ff][Yy]\d{2,4}|\d{4}s")
_KIND = re.compile(r"[a-z][a-z0-9_]{0,29}")


def _words(text: str) -> frozenset[str]:
    return frozenset(text.split())


# Words in a column name or key that say it identifies a person (HIPAA safe
# harbor: names, places smaller than a state, dates, contact details,
# record/account/licence numbers, device and vehicle ids, biometrics, photos).
_ID_WORDS = _words(
    """
    id ids mrn ssn sid pid uid umid emplid uniqname name names firstname lastname surname fullname
    middlename maiden nickname initials email mail phone tel fax contact address street city town
    county zip zipcode postcode postal fips tract geocode lat lon lng latitude longitude gps dob
    birth birthdate birthday date dates datetime timestamp ip url uuid guid record participant
    subject patient user username login device imei mac serial vin vehicle plate license licence
    account acct certificate beneficiary insurance passport biometric fingerprint voiceprint retina
    photo photos face facial
    """
)
_ID_COMPOUNDS = (
    "firstname", "lastname", "fullname", "dateofbirth", "birthdate", "zipcode", "postcode",
    "username", "studyid", "participantid", "subjectid", "patientid", "personid", "recordid",
    "memberid", "phonenumber", "emailaddress", "ipaddress", "streetaddress", "socialsecurity",
)  # fmt: skip
# Ordinary words ending in "id", which aren't identifiers.
_NOT_IDS = _words(
    """
    covid valid invalid rapid solid lipid lipids fluid fluids liquid liquids hybrid humid mid grid
    vivid timid candid rigid arid lucid placid pyramid paid unpaid prepaid said kid kids acid acids
    amid bid rid lid squid morbid tepid insipid avid livid florid horrid splendid intrepid sordid
    orchid forbid
    """
)


@dataclass(frozen=True)
class Verdict:
    path: str  # relative to out/, posix separators
    released: bool
    reason: str
    rows: int | None = None
    columns: int | None = None


class _Held(Exception):
    """The file is held; the message is the plain reason."""


def check_outbox(out: Path, *, min_cell: int = MIN_CELL) -> list[Verdict]:
    """Every file under out/ (recursively), each released or held."""
    return [verdict for verdict, _ in _check(out, min_cell)]


def apply(out: Path, released_dir: Path, held_dir: Path, *, min_cell: int = MIN_CELL) -> list[Verdict]:
    """check_outbox, then move each file into released_dir or held_dir keeping
    its relative path; manifest.json itself goes to held_dir. Returns the verdicts.

    A released file is checked again after the move: if it changed, it's held.
    Run this with the container stopped.
    """
    done = []
    for verdict, digest in _check(out, min_cell):
        source = out / verdict.path
        if verdict.released:
            target = released_dir / verdict.path
            if os.path.lexists(target):
                verdict = _hold(verdict, "a file with that name was already released")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(source, target)
                try:
                    same = hashlib.sha256(_read(target)).hexdigest() == digest
                except _Held:
                    same = False
                if same:
                    done.append(verdict)
                    continue
                verdict = _hold(verdict, "it changed while it was being checked")
                source = target
        target = _free(held_dir / verdict.path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(source, target)
        done.append(verdict)
    return done


def _hold(verdict: Verdict, reason: str) -> Verdict:
    return replace(verdict, released=False, reason=reason)


def _free(target: Path) -> Path:
    """target, or target.1, target.2, ... if it's taken: nothing held is overwritten."""
    candidate, n = target, 0
    while os.path.lexists(candidate):
        n += 1
        candidate = target.with_name(f"{target.name}.{n}")
    return candidate


def _check(out: Path, min_cell: int) -> list[tuple[Verdict, str | None]]:
    """The verdicts, each with the checked content's SHA-256 when released."""
    if not os.path.lexists(out):
        return []
    entries = _entries(out)
    linked = out.is_symlink()
    manifest = None if linked else _manifest(out)
    results: list[tuple[Verdict, str | None]] = []
    for rel, problem in entries:
        if rel == MANIFEST:
            results.append((Verdict(rel, False, "manifest.json stays with the held files"), None))
        elif linked:
            results.append((Verdict(rel, False, "the outbox folder is a link"), None))
        elif problem:
            results.append((Verdict(rel, False, problem), None))
        elif manifest is None:
            results.append((Verdict(rel, False, "no valid manifest.json"), None))
        elif (entry := manifest.get(rel)) is None:
            results.append((Verdict(rel, False, "not listed in manifest.json"), None))
        else:
            results.append(_check_file(out / rel, rel, entry, min_cell))
    return results


def _entries(out: Path) -> list[tuple[str, str | None]]:
    """Every file under out/ (and every linked or unreadable folder), with why
    it's held if that's already plain."""
    found: list[tuple[str, str | None]] = []

    def unreadable(error: OSError) -> None:
        if error.filename and Path(error.filename) != out:
            found.append((Path(error.filename).relative_to(out).as_posix(), "its folder couldn't be read"))

    for folder, dirs, files in os.walk(out, onerror=unreadable):  # doesn't follow links
        base = Path(folder)
        for name in dirs:
            if (base / name).is_symlink():
                found.append(((base / name).relative_to(out).as_posix(), "it's a link"))
        for name in files:
            path = base / name
            mode = os.lstat(path).st_mode
            problem = None
            if stat.S_ISLNK(mode):
                problem = "it's a link"
            elif not stat.S_ISREG(mode):
                problem = "not an ordinary file"
            found.append((path.relative_to(out).as_posix(), problem))
    return sorted(found)


def _manifest(out: Path) -> dict[str, dict[str, Any]] | None:
    """The manifest's entries by path, or None if it's missing or not valid."""
    try:
        data = json.loads(_text(_read(out / MANIFEST)))
    except (_Held, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not isinstance(files := data.get("files"), list):
        return None
    entries: dict[str, dict[str, Any]] = {}
    for entry in files:
        if not isinstance(entry, dict) or not isinstance(path := entry.get("path"), str):
            return None
        if not _safe_path(path):
            continue  # matches no file, so nothing is released by it
        entries[path] = {"duplicate": True} if path in entries else entry
    return entries


def _safe_path(path: str) -> bool:
    """A plain relative path inside out/: no '..', '.', empty parts, backslashes or drives."""
    if not path or path.startswith("/") or "\\" in path or ":" in path or "\x00" in path:
        return False
    return all(part not in ("", ".", "..") for part in path.split("/")) and PurePosixPath(path).parts != ()


def _check_file(path: Path, rel: str, entry: dict[str, Any], min_cell: int) -> tuple[Verdict, str | None]:
    if entry.get("duplicate"):
        return Verdict(rel, False, "listed more than once in manifest.json"), None
    kind = entry.get("kind")
    if kind not in AGGREGATE_KINDS:
        shown = kind if isinstance(kind, str) and _KIND.fullmatch(kind) else "this kind"
        return Verdict(rel, False, f"{shown}: can't be checked automatically; review it in UM-Codex"), None
    suffix = PurePosixPath(rel).suffix.lower()
    try:
        data = _read(path)
        text = _text(data)
        if kind == "aggregate_table":
            if suffix not in _TABLE_DELIMITERS:
                raise _Held("an aggregate table must be a .csv or .tsv file")
            verdict = _table(rel, text, _TABLE_DELIMITERS[suffix], entry.get("count_column"), min_cell)
        else:
            if suffix != ".json":
                raise _Held("aggregate JSON must be a .json file")
            verdict = _json(rel, text, entry.get("count_fields"), min_cell)
    except _Held as held:
        return Verdict(rel, False, str(held)), None
    return verdict, hashlib.sha256(data).hexdigest()


def _read(path: Path) -> bytes:
    """The file's bytes, not following a link; held if it's too big."""
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        fd = os.open(path, flags)
    except OSError as error:
        raise _Held("it couldn't be read (or it's a link)") from error
    with os.fdopen(fd, "rb") as file:
        if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
            raise _Held("not an ordinary file")
        data = file.read(_MAX_BYTES + 1)
    if len(data) > _MAX_BYTES:
        raise _Held("larger than 5 MB")
    return data


def _text(data: bytes) -> str:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise _Held("not UTF-8 text") from error
    if "\x00" in text:
        raise _Held("it has binary content")
    return text.removeprefix("﻿")


def _quote(name: str) -> str:
    """A refused column name or key, for a reason: printable and short."""
    name = _CONTROL.sub("", name)
    return repr(name if len(name) <= _MAX_QUOTED else name[: _MAX_QUOTED - 1] + "…")


# Names and labels


def _name_tokens(name: str) -> list[str]:
    spaced = re.sub(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", " ", name)
    spaced = re.sub(r"(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])", " ", spaced)
    return [token for token in re.split(r"[^a-z0-9]+", spaced.casefold()) if token]


def _identifier_name(name: str) -> bool:
    """Whether a column name or key looks like it names an identifier."""
    folded = name.casefold()
    if "identifier" in folded or "e-mail" in folded:
        return True
    tokens = _name_tokens(name)
    joined = "".join(tokens)
    if any(compound in joined for compound in _ID_COMPOUNDS):
        return True
    for token in tokens:
        stem = token.removesuffix("s")
        if token in _ID_WORDS or stem in _ID_WORDS:
            return True
        if stem.endswith("id") and stem not in _NOT_IDS and not stem.endswith(("oid", "aid")):
            return True
    return False


def _string_problem(text: str) -> str | None:
    """Why a label (or a name) can't go out, in a few words, or None."""
    if len(text) > _MAX_LABEL:
        return "long text"
    if _CONTROL.search(text):
        return "line breaks or control characters"
    if _SSN.search(text):
        return "Social Security-like numbers"
    if _IP.search(text):
        return "IP addresses"
    if _DATE.search(text):
        return "exact dates"
    if "@" in text:
        return "email addresses"
    if _URL.search(text):
        return "web addresses"
    if _PHONE.search(text):
        return "phone numbers"
    if _LONG_DIGITS.search(text):
        return "long runs of digits"
    for chunk in re.split(r"[^A-Za-z0-9]+", text):
        letters = any(c.isalpha() for c in chunk)
        if letters and sum(c.isdigit() for c in chunk) >= 3 and not _PERIOD.fullmatch(chunk):
            return "codes that look like IDs"
    return None


def _name_problem(name: str, what: str) -> str | None:
    """Why a column name or key is refused, or None. Only an identifier-like
    name is quoted; one that looks like a value isn't."""
    if _identifier_name(name):
        return f"{what} {_quote(name)} looks like an identifier"
    if not name.strip():
        return f"a {what} has no name"
    if problem := _string_problem(name):
        return f"a {what} name has {problem}"
    return None


def _age_like(name: str) -> bool:
    return "age" in _name_tokens(name)


def _number_problem(text: str) -> str | None:
    if _LONG_DIGITS.search(text.split(".")[0].split("e")[0].split("E")[0]):
        return "long runs of digits"
    return None


# aggregate_table


def _table(rel: str, text: str, delimiter: str, count_column: Any, min_cell: int) -> Verdict:
    try:
        rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True))
    except csv.Error as error:
        raise _Held("it couldn't be read as a table") from error
    while rows and not rows[-1]:
        rows.pop()
    if not rows:
        raise _Held("it's empty")
    header, data = rows[0], rows[1:]
    if not data:
        raise _Held("no data rows")
    if any(len(row) != len(header) for row in data):
        raise _Held("rows of different widths")
    if len(data) > _MAX_ROWS:
        raise _Held(f"more than {_MAX_ROWS:,} rows")
    if len(header) > _MAX_COLUMNS:
        raise _Held(f"more than {_MAX_COLUMNS} columns")
    if len({name.strip().casefold() for name in header}) != len(header):
        raise _Held("two columns have the same name")
    for name in header:
        if problem := _name_problem(name, "column"):
            raise _Held(problem)
    if not isinstance(count_column, str) or not count_column:
        raise _Held("manifest.json gives no count_column")
    if count_column not in header:
        raise _Held("the count column named in manifest.json isn't in the table")

    smallest = None
    for index, name in enumerate(header):
        values = [row[index].strip() for row in data]
        if name == count_column:
            smallest = _counts(values, min_cell)
        else:
            _column(name, values)
    return Verdict(
        rel, True, f"aggregate table, {len(data)} rows, smallest count {smallest}", len(data), len(header)
    )


def _counts(values: list[str], min_cell: int) -> int:
    if not all(_WHOLE.fullmatch(value) for value in values):
        raise _Held("count column has non-integers")
    counts = [int(value) for value in values]
    if min(counts) < min_cell:
        raise _Held(f"a count below {min_cell}")
    return min(counts)


def _column(name: str, values: list[str]) -> None:
    labels: set[str] = set()
    numbers: list[float] = []
    for value in values:
        if value.casefold() in _MISSING:
            continue
        if _NUMBER.fullmatch(value):
            if problem := _number_problem(value):
                raise _Held(f"column {_quote(name)} has {problem}")
            numbers.append(float(value))
        elif problem := _string_problem(value):
            raise _Held(f"column {_quote(name)} has {problem}")
        else:
            labels.add(value)
    if len(labels) > _MAX_LABELS:
        raise _Held(f"column {_quote(name)} has more than {_MAX_LABELS} different labels (free text or IDs?)")
    whole = [n for n in numbers if n == int(n)] if all(abs(n) != float("inf") for n in numbers) else []
    if len(numbers) > _ID_LIKE_ROWS and len(whole) == len(numbers) and len(set(whole)) == len(whole):
        raise _Held(f"column {_quote(name)} has all-different whole numbers (IDs?)")
    if _age_like(name) and any(n > _OLDEST_AGE for n in numbers):
        raise _Held(f"column {_quote(name)} has ages over {_OLDEST_AGE}")


# aggregate_json


def _unique_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    if len({key for key, _ in pairs}) != len(pairs):
        raise _Held("a key appears twice in one object")
    return dict(pairs)


class _JsonCheck:
    def __init__(self, count_fields: set[str], min_cell: int) -> None:
        self.count_fields = count_fields
        self.min_cell = min_cell
        self.counts: list[int] = []
        self.leaves = 0
        self.labels: dict[str, set[str]] = {}

    def walk(self, value: Any, depth: int, key: str) -> None:
        if isinstance(value, dict | list):
            if depth >= _MAX_DEPTH:
                raise _Held("nested too deeply")
            if isinstance(value, list):
                for item in value:
                    self.walk(item, depth + 1, key)
                return
            grouping = 0
            for name, item in value.items():
                if problem := _name_problem(name, "key"):
                    raise _Held(problem)
                if name.isdigit() and len(name) >= 5:
                    raise _Held("a key is a long number")
                if name in self.count_fields:
                    self.count(item)
                    continue
                if isinstance(item, dict | list):
                    grouping += 1
                self.walk(item, depth + 1, name)
            if grouping > _MAX_LABELS:
                raise _Held(f"an object has more than {_MAX_LABELS} groups (free text or IDs?)")
            return
        self.leaves += 1
        if self.leaves > _MAX_LEAVES:
            raise _Held(f"more than {_MAX_LEAVES:,} values")
        if isinstance(value, str):
            if value.strip().casefold() in _MISSING:
                return
            if problem := _string_problem(value):
                raise _Held(f"values under key {_quote(key)} have {problem}")
            labels = self.labels.setdefault(key, set())
            labels.add(value)
            if len(labels) > _MAX_LABELS:
                raise _Held(
                    f"key {_quote(key)} has more than {_MAX_LABELS} different labels (free text or IDs?)"
                )
        elif isinstance(value, int | float) and not isinstance(value, bool):
            if problem := _number_problem(repr(abs(value))):
                raise _Held(f"values under key {_quote(key)} have {problem}")
            if _age_like(key) and value > _OLDEST_AGE:
                raise _Held(f"key {_quote(key)} has ages over {_OLDEST_AGE}")
        elif value is not None and not isinstance(value, bool):
            raise _Held("a value of an unexpected type")

    def count(self, value: Any) -> None:
        if not isinstance(value, int) or isinstance(value, bool):
            raise _Held("a count field has a non-integer")
        if value < self.min_cell:
            raise _Held(f"a count below {self.min_cell}")
        self.leaves += 1
        self.counts.append(value)


def _json(rel: str, text: str, count_fields: Any, min_cell: int) -> Verdict:
    if not isinstance(count_fields, list) or not all(isinstance(f, str) and f for f in count_fields):
        raise _Held("manifest.json gives no count_fields")
    try:
        value = json.loads(text, object_pairs_hook=_unique_keys)
    except RecursionError as error:
        raise _Held("nested too deeply") from error
    except ValueError as error:
        raise _Held("it isn't valid JSON") from error
    if not (
        isinstance(value, dict)
        or (value and isinstance(value, list) and all(isinstance(v, dict) for v in value))
    ):
        raise _Held("aggregate JSON must be an object or a list of objects")
    check = _JsonCheck(set(count_fields), min_cell)
    check.walk(value, 0, "")
    if not check.counts:
        raise _Held("no counts, so cell sizes can't be checked")
    return Verdict(
        rel, True, f"aggregate JSON, {len(check.counts)} counts, smallest count {min(check.counts)}"
    )
