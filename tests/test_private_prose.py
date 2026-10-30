"""Stated rule (owner): block only the owner's own holdings and sizes; what a poster publicly shares about their own
portfolio, weights or positions is theirs and may be published, attributed."""
import pytest

from sigma.ranked import forbidden_key, private_hits


@pytest.mark.parametrize("text", [
    "@someone says their portfolio weights are 40% NVDA, 30% cash, shared in a public post",
    "A guest said my position size in the name is about 5% of my portfolio",
    "Poster argued a 10% position in AMD is too small",
    "Weights shared by the poster: NVDA 40%",
])
def test_a_poster_attributed_weight_or_position_is_allowed(text):
    assert private_hits({"claim": text}) == []
    assert forbidden_key({"claim": text, "items": [{"reason": text}]}) is None


@pytest.mark.parametrize("text", [
    "our portfolio holds NVDA", "the owner's holdings are mostly semis", "the maintainer's position size is 5%",
    "up 12% of our portfolio", "our cost basis is $31", "we own shares of AMD", "see /Users/someone/notes.md",
])
def test_the_owners_own_holdings_and_sizes_are_blocked(text):
    assert private_hits({"claim": text})


def test_a_holdings_style_field_name_is_blocked_but_text_starting_with_the_word_is_not():
    assert forbidden_key({"episodes": [{"holdings": []}]}) == "holding"
    assert forbidden_key({"x": {"weight": 0.4}}) == "weight"
    assert forbidden_key({"claim": "weight gains were discussed"}) is None
