from pathlib import Path

from crawler.extract import looks_like_name, looks_like_title, parse_page

FIXTURES = Path(__file__).parent / "fixtures"


def people(name):
    return {p.name: p for p in parse_page((FIXTURES / name).read_text()).people}


def test_name_and_title_heuristics():
    assert looks_like_name("Ana López")
    assert looks_like_name("Luis de la Garza")
    assert not looks_like_name("Meet the Team")
    assert not looks_like_name("Chief Executive Officer")
    assert not looks_like_name("ana lopez")
    assert looks_like_title("VP of Engineering")
    assert not looks_like_title("Privacy")


def test_extracts_team_cards():
    found = people("team_cards.html")
    assert found["Ana López"].title == "Chief Executive Officer"
    assert found["Luis de la Garza"].title == "VP of Engineering"
    assert found["Priya Raman"].title == "Head of Revenue Operations"
    assert found["Sara Kim"].title == "Senior Data Engineer"
    assert all(p.method == "html" for p in found.values())


def test_person_without_title_is_skipped_and_scripts_are_ignored():
    found = people("team_cards.html")
    assert "Tom Becker" not in found
    assert "Not A Person" not in found


def test_extracts_links():
    links = parse_page((FIXTURES / "team_cards.html").read_text()).links
    assert "/about" in links
    assert "https://linkedin.com/in/ana" in links


def test_jsonld_people_including_nested_and_graph():
    found = people("jsonld.html")
    assert found["Luis Garza"].title == "Co-Founder & CEO"
    assert found["Maria Torres"].method == "jsonld"
    assert "No Title Person" not in found


def test_jsonld_wins_over_html_for_same_person():
    assert people("jsonld.html")["Maria Torres"].title == "Head of Sales"
