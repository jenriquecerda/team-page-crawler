import csv
import io
import json
from contextlib import redirect_stdout

from crawler.cli import build_parser, format_report, main
from crawler.crawl import DomainReport
from crawler.extract import Person
from crawler.store import Diff, Store


def test_parser_defaults():
    args = build_parser().parse_args(["crawl", "acme.com"])
    assert args.domains == ["acme.com"]
    assert args.max_pages == 25
    assert args.delay == 1.0


def test_format_report_shows_diff_and_errors():
    report = DomainReport(
        "acme.com",
        pages_fetched=3,
        people=[Person("Ana Lopez", "CEO", "html", 0.7)],
        diff=Diff(added=["Ana Lopez"], removed=["Sara Kim"],
                  title_changed=[("Raj Patel", "CTO", "CEO")]),
        errors=["https://acme.com/team: HTTP 503"],
        complete=False,
    )
    text = format_report(report)
    assert "(incomplete)" in text
    assert "+ Ana Lopez" in text
    assert "- Sara Kim" in text
    assert "~ Raj Patel: CTO -> CEO" in text
    assert "! https://acme.com/team: HTTP 503" in text


def _seeded_db(tmp_path):
    db = tmp_path / "test.db"
    Store(db).sync_people("acme.com", [(Person("Ana Lopez", "CEO", "jsonld", 0.95), "u")])
    return str(db)


def _run(argv):
    out = io.StringIO()
    with redirect_stdout(out):
        code = main(argv)
    return code, out.getvalue()


def test_export_csv(tmp_path):
    code, out = _run(["--db", _seeded_db(tmp_path), "export"])
    assert code == 0
    rows = list(csv.DictReader(io.StringIO(out)))
    assert rows[0]["name"] == "Ana Lopez"
    assert rows[0]["method"] == "jsonld"


def test_export_json_filtered_by_domain(tmp_path):
    db = _seeded_db(tmp_path)
    assert json.loads(_run(["--db", db, "export", "--format", "json"])[1])[0]["title"] == "CEO"
    assert json.loads(_run(["--db", db, "export", "--domain", "other.com",
                            "--format", "json"])[1]) == []
