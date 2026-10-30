from sigma import creators


def test_registry_points_only_at_listed_sources_and_handles():
    """Stated rule (creators.py docstring): every outlet is in sources.yaml or x-accounts.json, and belongs to one creator.
    A pull request that adds a typo'd handle or a second owner for a channel must fail here, not on the creator's page."""
    assert creators.problems({"creators": [{"id": "a", "name": "A", "sources": ["s1"], "x": ["Hand"]}]}, ["s1"], ["Hand"]) == []
    raw = {"creators": [{"id": "a", "name": "A", "sources": ["s1", "gone"], "x": ["Hand"]},
                        {"id": "b", "name": "B", "sources": ["s1"], "x": ["hand", "nobody"]}]}
    assert creators.problems(raw, ["s1"], ["Hand"]) == [
        'a: source "gone" is not in sources.yaml', 'b: source "s1" is already a\'s',
        'b: X handle "hand" is already a\'s', 'b: X handle "nobody" is not in x-accounts.json']
