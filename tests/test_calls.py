import subprocess
import sys
from pathlib import Path

import pytest

from wire import calls

SPY = {"2026-10-20": 100, "2026-10-21": 100, "2026-10-22": 100, "2026-10-23": 100, "2026-10-26": 101, "2026-10-27": 102,
       "2026-10-28": 104, "2026-10-29": 104, "2026-10-30": 105}
STOCK = {"2026-10-23": 50, "2026-10-26": 49, "2026-10-30": 55}


def test_follow_signs_the_excess_over_spy_by_side_from_the_last_close_on_or_before_the_call():
    """outside-value, by hand: a Saturday call starts at Friday 10-23's close (50 / SPY 100). 5 trading days on, 10-30: stock
    55 is +10%, SPY 105 is +5%, excess +5%: a hit for a buy, a miss of the same size for a sell. 1 day on, 10-26: -2% against
    SPY +1%, excess -3%. The 21-day horizon has not elapsed, so it is absent."""
    buy = calls.follow({"date": "2026-10-24", "stance": 2}, STOCK, SPY)
    sell = calls.follow({"date": "2026-10-24", "stance": -1}, STOCK, SPY)
    assert sorted(buy) == [5] and buy[5]["signed"] == pytest.approx(0.05) and sell[5]["signed"] == pytest.approx(-0.05)
    assert calls.follow({"date": "2026-10-24", "stance": 1}, STOCK, {**SPY, "2026-10-26": 101})[5]["excess"] == pytest.approx(0.05)
    assert calls.follow({"date": "2026-10-24", "stance": 1}, {"2026-10-26": 49}, SPY) == {}  # no close on the entry day: no return


def test_the_site_path_cannot_reach_the_ledger():
    """stated rule: creator track records never reach the site or published/. Building the site must not
    load the ledger module, so nothing in it can read data/calls or the private creators file."""
    code = "import wire.site, sys; sys.exit('wire.calls' in sys.modules)"
    assert subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent.parent).returncode == 0


def test_a_call_counts_toward_the_creator_only_when_the_speaker_is_the_creator_or_a_host():
    """stated rule, speaker strings as they stand in published claims: the creator's name, "host", a
    listed host's name ("Paul") and "Paul (host)" are the creator's; a named guest, "guest host" and a blank speaker are not
    and land in the show's guest bucket."""
    from wire import creators

    chip = creators.Creator("chip-stock-investor", "Chip Stock Investor", ["chip-stock-investor"], [])
    money = creators.Creator("everything-money", "Everything Money", ["everything-money"], [], ["Paul"])
    owner = calls.owner_of([chip, money], {"chip-stock-investor": ["Chip Stock Investor"], "everything-money": ["Everything Money"]}, {})

    def credit(show, who):
        return owner({"kind": "social", "where": show, "who": who})[1]

    for show, who, own in [("Chip Stock Investor", "host", "chip-stock-investor"), ("Chip Stock Investor", "Chip Stock Investor", "chip-stock-investor"),
                           ("Everything Money", "Paul (host)", "everything-money"), ("Everything Money", "Paul", "everything-money"),
                           ("Everything Money", "co-host", "everything-money")]:
        assert credit(show, who) == own, (show, who)
    for show, who in [("Chip Stock Investor", "Shalini Sharma"), ("Chip Stock Investor", "guest host"), ("Chip Stock Investor", ""),
                      ("Everything Money", "Mo")]:
        assert credit(show, who).split("/")[1] == "guest", (show, who)
    assert credit("Chip Stock Investor", "Shalini Sharma") == "chip-stock-investor/guest/chip-stock-investor"
