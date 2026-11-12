import json

import pytest

from sigma.people import Person
from sigma.speakers import record_run

JENSEN = Person("Jensen Huang", "NVIDIA CEO", "core", kind="operator")
SOSIN = Person("Cliff Sosin", "CAS Investment Partners founder", "watch", ["Clifford Sosin"], kind="fund manager",
               links=[{"label": "Portfolio (13F)", "url": "https://example.com/p"}], fund={"name": "CAS Investment Partners", "cik": "0001697591"})
DESCRIPTION = "Cliff Sosin is the founder of CAS Investment Partners. We also discuss Jensen Huang and Nvidia."


def run_with(tmp_path, reader):
    (tmp_path / "rank").mkdir()
    (tmp_path / "ep.md").write_text("# Title\n\n## Description\n\n" + DESCRIPTION + "\n\nHost: welcome Clifford Sosin. He once met Jane Roe.")
    (tmp_path / "manifest.json").write_text(json.dumps({"episodes": [{"episode_id": "rss:1", "title": "Cliff Sosin on AI", "description": DESCRIPTION,
                                                                      "file": "ep.md"}]}))
    (tmp_path / "rank" / "batch-1-out.json").write_text(json.dumps([{"episode_id": "rss:1", "speakers": reader}]))
    record_run(tmp_path, [JENSEN, SOSIN])
    return json.loads((tmp_path / "manifest.json").read_text())["episodes"][0].get("speakers")


def test_only_the_reader_names_a_speaker_and_a_listed_name_gets_the_profile(tmp_path):
    """Failure seen in the review of d880a20: Jensen Huang was 'speaking' in episodes that only discuss him."""
    rows = run_with(tmp_path, ["Clifford Sosin", {"name": "Jane Roe", "role": "former Goldman Sachs partner convicted of fraud"}])
    assert [r["name"] for r in rows] == ["Cliff Sosin", "Jane Roe"]
    assert rows[0]["kind"] == "fund manager" and rows[0]["fund"]["cik"] == "0001697591" and rows[0]["links"][0]["label"] == "Portfolio (13F)"
    assert "role" not in rows[1]


@pytest.mark.parametrize("bad", [["Sosin"], [{"name": "Jane Roe Smith"}], [7]])
def test_a_first_name_alone_a_name_not_in_the_text_or_a_non_name_stops_the_merge(tmp_path, bad):
    with pytest.raises(ValueError):
        run_with(tmp_path, bad)
