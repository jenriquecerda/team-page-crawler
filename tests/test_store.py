from crawler.extract import Person
from crawler.store import Store


def p(name, title):
    return Person(name, title, "html", 0.7)


URL = "https://acme.com/team"


def test_first_crawl_adds_everyone():
    store = Store()
    diff = store.sync_people(
        "acme.com", [(p("Ana Lopez", "CEO"), URL), (p("Sara Kim", "CTO"), URL)]
    )
    assert sorted(diff.added) == ["Ana Lopez", "Sara Kim"]
    assert len(store.export_rows("acme.com")) == 2


def test_second_crawl_reports_title_changes_and_departures():
    store = Store()
    store.sync_people("acme.com", [(p("Ana Lopez", "CTO"), URL), (p("Sara Kim", "VP Eng"), URL)])
    diff = store.sync_people(
        "acme.com", [(p("Ana Lopez", "CEO"), URL), (p("Raj Patel", "CFO"), URL)]
    )
    assert diff.added == ["Raj Patel"]
    assert diff.removed == ["Sara Kim"]
    assert diff.title_changed == [("Ana Lopez", "CTO", "CEO")]
    names = {r["name"] for r in store.export_rows("acme.com")}
    assert names == {"Ana Lopez", "Raj Patel"}


def test_incomplete_crawl_does_not_remove_people():
    store = Store()
    store.sync_people("acme.com", [(p("Ana Lopez", "CEO"), URL)])
    diff = store.sync_people("acme.com", [], complete=False)
    assert diff.empty
    assert len(store.export_rows("acme.com")) == 1


def test_unchanged_crawl_has_empty_diff():
    store = Store()
    store.sync_people("acme.com", [(p("Ana Lopez", "CEO"), URL)])
    assert store.sync_people("acme.com", [(p("Ana Lopez", "CEO"), URL)]).empty


def test_page_hash_detects_unchanged_content():
    store = Store()
    store.save_page(URL, "acme.com", 200, "<html>v1</html>")
    assert store.page_unchanged(URL, "<html>v1</html>")
    assert not store.page_unchanged(URL, "<html>v2</html>")
