from crawler.frontier import Frontier
from crawler.urls import normalize_url, same_site, team_score


def test_normalize_resolves_relative_and_drops_fragment():
    assert normalize_url("../team#top", "https://Acme.com/about/x") == "https://acme.com/team"


def test_normalize_drops_default_port_and_rejects_other_schemes():
    assert normalize_url("https://acme.com:443/a") == "https://acme.com/a"
    assert normalize_url("https://acme.com:8443/a") == "https://acme.com:8443/a"
    assert normalize_url("mailto:hi@acme.com") is None
    assert normalize_url("javascript:void(0)") is None


def test_same_site_ignores_www():
    assert same_site("https://www.acme.com/x", "https://acme.com")
    assert not same_site("https://evil.com/acme.com", "https://acme.com")


def test_team_pages_score_higher():
    assert team_score("https://acme.com/about/team") > team_score("https://acme.com/blog/post-1")
    assert team_score("https://acme.com/leadership") > team_score("https://acme.com/pricing")


def test_frontier_prioritizes_team_pages_and_dedupes():
    f = Frontier("https://acme.com", max_pages=10)
    f.add("/blog", 1, base="https://acme.com/")
    f.add("/team", 1, base="https://acme.com/")
    f.add("/team#bios", 1, base="https://acme.com/")
    assert len(f) == 2
    assert f.pop()[0] == "https://acme.com/team"


def test_frontier_enforces_scope_depth_and_budget():
    f = Frontier("https://acme.com", max_pages=1, max_depth=1)
    assert not f.add("https://other.com/team", 1)
    assert not f.add("https://acme.com/logo.png", 1)
    assert not f.add("https://acme.com/deep", 2)
    f.add("https://acme.com/a", 1)
    f.add("https://acme.com/b", 1)
    assert f.pop() is not None
    assert f.pop() is None
