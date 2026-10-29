"""The daily X edition: grounding and what reaches the public file. Rules from AGENTS.md ("every claim is grounded",
"never commit copied text") and the X edition's stated rules."""
import json
from datetime import datetime


def test_an_edition_publishes_only_numbers_its_cited_posts_state_and_never_the_post_text(monkeypatch, tmp_path):
    """stated-rule (AGENTS.md "every claim is grounded"): a figure must be in the cited post's text,
    and the public file carries ids and Sigma's sentences, never the authors' text. The raw U+2028 in the text is
    failure-seen: the scanner's first scan reported that it broke the scan reader."""
    from sigma import xdaily

    monkeypatch.setenv("SIGMA_X_DIR", str(tmp_path))
    (tmp_path / "accounts.json").write_text(json.dumps({"accounts": [{"handle": "someanalyst", "tier": "core", "type": "news"}]}))
    monkeypatch.setattr(xdaily, "ACCOUNTS", tmp_path / "accounts.json")
    sd = tmp_path / "scan" / "2026-10-26"
    sd.mkdir(parents=True)
    text = "Anthropic S-1: H1 revenue $16.3B, compute commitments of $265.6B with Google, Amazon and Microsoft."
    post = {"id": "2114705686513033360", "handle": "someanalyst", "created_at": "2026-10-26T13:08:00Z", "text": text,
            "metrics": {"like": 10, "repost": 1}, "media": [{"type": "photo"}]}
    nulls = {**post, "id": "2114705686513033361", "lang": None, "conversation_id": None}  # X sometimes returns neither: both are optional
    (sd / "posts.jsonl").write_text("\n".join(json.dumps(p, ensure_ascii=False) for p in (post, nulls)) + "\n", encoding="utf-8")
    (sd / "quoted.jsonl").write_text("")
    (sd / "manifest.json").write_text(json.dumps({"date": "2026-10-26", "window_start": "2026-10-25T14:00:00Z",
        "window_end": "2026-10-26T14:00:00Z", "accounts_requested": 1, "accounts_ok": 1, "accounts_failed": [], "calls": 1,
        "rate_limited": False, "complete": True, "scanner": "test", "tool": "test"}))
    assert xdaily.scan_problems("2026-10-26") == []
    # stated-rule: the delivery check refuses a manifest at another contract_version
    # (a scanner on a stale skills/x-scan/SKILL.md); readers (status, prep) still accept an older scan
    man_p = sd / "manifest.json"
    man = json.loads(man_p.read_text())
    assert any("contract_version" in p for p in xdaily.scan_problems("2026-10-26", contract=True))
    man_p.write_text(json.dumps({**man, "contract_version": xdaily.contract_version() + 1}))
    assert any("contract_version" in p for p in xdaily.scan_problems("2026-10-26", contract=True))
    man_p.write_text(json.dumps({**man, "contract_version": xdaily.contract_version()}))
    assert xdaily.scan_problems("2026-10-26", contract=True) == []
    man_p.write_text(json.dumps(man))
    # stated-rule: an account's type is one of a fixed set; a list with any other is refused
    for bad in ({"type": "views"}, {"type": "howto"}, {}, {"type": "news", "type2": "news"}, {"type": "news", "lens": "si"}):
        (tmp_path / "accounts.json").write_text(json.dumps({"accounts": [{"handle": "someanalyst", "tier": "core", **bad}]}))
        assert any("@someanalyst" in p for p in xdaily.scan_problems("2026-10-26")), bad
    (tmp_path / "accounts.json").write_text(json.dumps({"accounts": [{"handle": "someanalyst", "tier": "core", "type": "news"}]}))
    ed = {"date": "2026-10-26", "signals": [{"text": "Posters fixed on $300B of compute commitments in the S-1.", "cites": [post["id"]]}],
          "posts": [{"id": post["id"]}]}
    errs, _ = xdaily.edition_problems("2026-10-26", ed)
    assert len(errs) == 1 and "$300B" in errs[0]  # the chart-free text says 265.6B, so 300B has no source
    ed["signals"][0]["text"] = "Posters fixed on $265.6B of compute commitments and $16.3B of first-half revenue."
    assert xdaily.edition_problems("2026-10-26", ed) == ([], [])
    out = json.dumps(xdaily.public_edition("2026-10-26", ed))
    assert "Microsoft" not in out and post["id"] in out
    assert xdaily.edition_problems("2026-10-26", {**ed, "si": []})[0][0].startswith("schema:")
    assert xdaily.edition_problems("2026-10-26", {**ed, "posts": [{"id": post["id"], "lens": "signals"}]})[0][0].startswith("schema:")


def test_a_post_the_scan_reports_gone_leaves_every_file_sigma_keeps_and_the_next_check_list(monkeypatch, tmp_path):
    """failure-seen (Codex P1: the publication source-projection gate rejected the stale edition after prune): X's
    deletion rule removes the gone id everywhere Sigma keeps it, refreshes the surviving public projection, and a second
    run changes nothing."""
    import pytest

    from sigma import entities, published, signals_index, stance, xdaily, xprune

    gone, kept, thread = "2114775956821061744", "2114752489476309203", "2114881103018574324"
    unlabelled_gone = "2114775956821061745"
    more_gone, more_kept = "2114999999999999990", "2114999999999999991"
    x, pub = tmp_path / "x", tmp_path / "published"
    monkeypatch.setenv("SIGMA_X_DIR", str(x))
    local_data = tmp_path / "local-data"
    local_data.mkdir()
    accounts = local_data / "x-accounts.json"
    accounts.write_text(json.dumps({"accounts": [{"handle": "h", "tier": "core", "type": "news"}]}))
    (local_data / "entities.json").write_text("{}")
    monkeypatch.setattr(xdaily, "ACCOUNTS", accounts)
    monkeypatch.setattr(signals_index, "DATA", local_data)
    monkeypatch.setattr(entities, "ENTITIES_FILE", local_data / "entities.json")
    (x / "scan/2026-10-26").mkdir(parents=True)
    (x / "days/2026-10-26").mkdir(parents=True)
    (pub / "x/editions").mkdir(parents=True)
    (pub / "x/stances").mkdir(parents=True)
    scan = [{"id": i, "handle": "h", "created_at": "2026-10-26T12:00:00Z",
             "text": "The Fed may change interest rates tomorrow." if i == gone else f"A sufficiently long synthetic source post for {i}",
             "metrics": {"like": 10}}
            for i in (gone, kept, thread, more_gone, more_kept)]
    for post in scan:
        if post["id"] in {thread, more_gone}:
            post.update({"in_reply_to_id": kept, "in_reply_to_handle": "h"})
    (x / "scan/2026-10-26/posts.jsonl").write_text("\n".join(json.dumps(p) for p in scan) + "\n")
    (x / "scan/2026-10-26/quoted.jsonl").write_text("")
    (x / "scan/2026-10-26/manifest.json").write_text(json.dumps({"ids_checked": 5, "ids_gone": [gone, more_gone, unlabelled_gone],
        "date": "2026-10-26", "window_start": "2026-10-25T12:00:00Z", "window_end": "2026-10-26T12:00:00Z",
        "accounts_ok": 1, "accounts_requested": 1}))
    (x / "days/2026-10-26/prep.md").write_text(f"# scan\n\n## {gone} @h 10-26\ntext of {gone}\n\n## {kept} @h 10-26\ntext of {kept}\n")
    ed = {"date": "2026-10-26", "headline": "h", "signals": [{"text": "Both posts argue for one thing.", "cites": [gone, kept]},
                                                            {"text": "A second point about another thing.", "cites": [kept]}],
          "posts": [{"id": gone}, {"id": kept}]}
    (x / "days/2026-10-26/edition.json").write_text(json.dumps(ed))
    (pub / "x/editions/2026-10-26.json").write_text(json.dumps(xdaily.public_edition("2026-10-26", ed)))
    previous, previous_selected = "2026-10-25", "2114666666666666601"
    previous_more_ids = [str(2114666666666666700 + i) for i in range(31)]
    previous_more = previous_more_ids[0]
    previous_scan = x / "scan" / previous
    previous_scan.mkdir()
    previous_posts = [
        {"id": unlabelled_gone, "handle": "h", "created_at": previous + "T12:00:00Z", "text": "The Fed may change interest rates tomorrow.", "metrics": {"like": 0}},
        {"id": previous_selected, "handle": "h", "created_at": previous + "T12:00:00Z", "text": "A sufficiently long synthetic source post.", "metrics": {"like": 10}},
        *[{"id": i, "handle": "h", "created_at": previous + "T12:00:00Z", "text": "A sufficiently long synthetic source post.", "metrics": {"like": 100}}
          for i in previous_more_ids],
    ]
    (previous_scan / "posts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in previous_posts))
    (previous_scan / "quoted.jsonl").write_text("")
    (previous_scan / "manifest.json").write_text(json.dumps({"date": previous, "window_start": "2026-10-24T12:00:00Z",
        "window_end": previous + "T12:00:00Z", "accounts_ok": 1, "accounts_requested": 1}))
    (x / "days" / previous).mkdir()
    previous_ed = {"date": previous, "signals": [{"text": "Readers discuss a changing market event today.", "cites": [previous_selected]}],
                   "posts": [{"id": previous_selected}]}
    (x / "days" / previous / "edition.json").write_text(json.dumps(previous_ed))
    (pub / "x/editions" / f"{previous}.json").write_text(json.dumps(xdaily.public_edition(previous, previous_ed)))
    previous_public = json.loads((pub / "x/editions" / f"{previous}.json").read_text())
    assert previous_public["posts_read"] == 33
    assert unlabelled_gone not in {p["id"] for p in [*previous_public["posts"], *previous_public["more"]]}
    assert len(previous_public["more"]) == 30 and previous_more in {p["id"] for p in previous_public["more"]}
    xlabel = [{"ticker": "@MARKET", "stance": 1, "reason": "Rates remain important"}]
    neutral = [{"ticker": "@MARKET", "stance": 0, "reason": "No directional call"}]
    rows = [{"key": f"p-{gone}", "labels": xlabel, "id": gone, "handle": "h", "date": "2026-10-26"},
            {"key": f"p-{kept}", "labels": xlabel, "id": kept, "handle": "h", "date": "2026-10-26", "thread": [thread, more_gone]},
            {"key": stance.x_key("2026-10-26", "signals", 1, ed["signals"][1]["text"]), "labels": neutral, "market": True}]
    (pub / "x/stances/2026-10-26.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    previous_stance = {"key": f"p-{previous_selected}", "labels": xlabel, "id": previous_selected, "handle": "h", "date": previous}
    (pub / "x/stances" / f"{previous}.jsonl").write_text(json.dumps(previous_stance) + "\n")

    (pub / "signals").mkdir()
    generated = datetime.fromisoformat("2026-10-29T12:00:00-07:00")
    for day in ("2026-10-26", previous):
        (pub / "signals" / f"{day}.json").write_text(json.dumps(signals_index.build(day, pub, now=generated)))
    previous_before = json.loads((pub / "signals" / f"{previous}.json").read_text())
    assert not previous_before["complete"] and [m["source"] for m in previous_before["missing"]] == ["x"]

    def validate_projection():
        published.validate_publication_outputs(pub, x)

    validate_projection()

    def mentions():
        return sorted(str(f.relative_to(tmp_path)) for f in tmp_path.rglob("*") if f.is_file() and gone in f.read_text())

    def mentions_more_gone():
        return sorted(str(f.relative_to(tmp_path)) for f in tmp_path.rglob("*") if f.is_file() and more_gone in f.read_text())

    assert len(mentions()) == 7
    assert len(mentions_more_gone()) == 4
    args = type("A", (), {"date": "2026-10-26", "published": str(pub), "force": False})
    previous_source_path = x / "days" / previous / "edition.json"
    previous_source_bytes = previous_source_path.read_bytes()
    previous_source_path.unlink()
    before_refusal = {f: f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}
    with pytest.raises(SystemExit, match="private edition is missing"):
        xprune.prune_cmd(args)
    assert before_refusal == {f: f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}
    previous_source_path.write_bytes(previous_source_bytes)
    xprune.prune_cmd(args)
    assert mentions() == ["x/scan/2026-10-26/manifest.json"]  # the scanner's own report stays
    after = json.loads((pub / "x/editions/2026-10-26.json").read_text())
    assert [s["cites"] for s in after["signals"]] == [[kept]] and [p["id"] for p in after["posts"]] == [kept]
    assert [p["id"] for p in after["more"]] == [thread, more_kept]
    source = json.loads((x / "days/2026-10-26/edition.json").read_text())
    assert after == xdaily.public_edition("2026-10-26", source)
    assert after["posts_read"] == 3
    previous_after = json.loads((pub / "x/editions" / f"{previous}.json").read_text())
    previous_source = json.loads((x / "days" / previous / "edition.json").read_text())
    assert previous_after == xdaily.public_edition(previous, previous_source)
    assert previous_after["posts_read"] == 32
    assert previous_after["more"] == previous_public["more"]
    validate_projection()
    current_stances = [json.loads(line) for line in (pub / "x/stances/2026-10-26.jsonl").read_text().splitlines()]
    assert current_stances[0] == {**rows[1], "thread": [thread]}
    assert current_stances[1] == {**rows[2], "key": stance.x_key("2026-10-26", "signals", 0, ed["signals"][1]["text"])}
    previous_signal = json.loads((pub / "signals" / f"{previous}.json").read_text())
    assert previous_signal["complete"] and previous_signal["missing"] == []
    assert current_stances[1]["labels"] == neutral
    current_signal = json.loads((pub / "signals/2026-10-26.json").read_text())
    assert [r["source_id"] for r in current_signal["signals"] if r["source_kind"] == "x"] == [kept]
    assert current_signal["generated_at"] == generated.isoformat(timespec="minutes")
    assert previous_signal["generated_at"] == generated.isoformat(timespec="minutes")
    index = json.loads((pub / "signals/index.json").read_text())
    assert next(r for r in index["days"] if r["date"] == previous)["complete"] is True
    expected_ids = [kept, thread, more_kept, previous_selected, *[p["id"] for p in previous_public["more"]]]
    assert json.loads((x / "check-ids.json").read_text())["ids"] == sorted(expected_ids)
    assert sorted(str(f.relative_to(tmp_path)) for f in tmp_path.rglob("*")
                  if f.is_file() and unlabelled_gone in f.read_text()) == ["x/scan/2026-10-26/manifest.json"]
    assert mentions_more_gone() == ["x/scan/2026-10-26/manifest.json"]
    before = {f: f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}
    xprune.prune_cmd(args)
    assert before == {f: f.read_bytes() for f in tmp_path.rglob("*") if f.is_file()}


def test_a_day_is_rebuilt_when_the_scan_grows_after_its_edition_and_done_again_once_republished(monkeypatch, tmp_path):
    """stated-rule (AGENTS.md "any step runs by hand, any time", on-demand X updates): a second scan of
    a day moves the manifest's window_end on; status must then say prep, not done, and say done again once the new
    edition replaces the published one."""
    from argparse import Namespace

    from sigma import xdaily

    x, pub = tmp_path / "x", tmp_path / "pub"
    monkeypatch.setenv("SIGMA_X_DIR", str(x))
    (tmp_path / "accounts.json").write_text(json.dumps({"accounts": [{"handle": "someanalyst", "tier": "core", "type": "news"}]}))
    monkeypatch.setattr(xdaily, "ACCOUNTS", tmp_path / "accounts.json")
    d, sd = "2026-10-26", x / "scan" / "2026-10-26"
    sd.mkdir(parents=True)
    posts = [{"id": "2114705686513033360", "handle": "someanalyst", "created_at": "2026-10-26T13:08:00Z",
              "text": "Plain words about the market today and nothing else here.", "metrics": {"like": 3}},
             {"id": "2114705686513033361", "handle": "someanalyst", "created_at": "2026-10-26T15:30:00Z",
              "text": "A later post about rates and what the desk is watching.", "metrics": {"like": 4}}]

    def scan(n, end):
        # failure-seen (coordinator, 2026-10-27): a scan holding posts by an account since cut from the list must still prep
        cut = {"id": "2114705686513033399", "handle": "cutlater", "created_at": "2026-10-26T14:00:00Z",
               "text": "A post by an account that is no longer listed, long enough to count.", "metrics": {"like": 1}}
        (sd / "posts.jsonl").write_text("".join(json.dumps(p) + "\n" for p in [*posts[:n], cut]))
        (sd / "quoted.jsonl").write_text("")
        (sd / "manifest.json").write_text(json.dumps({"date": d, "window_start": "2026-10-25T14:00:00Z", "window_end": end,
            "accounts_requested": 1, "accounts_ok": 1, "accounts_failed": [], "calls": 1, "rate_limited": False,
            "complete": True, "scanner": "test", "tool": "test"}))

    def build():
        args = Namespace(date=d, keep=250, published=str(pub))
        xdaily.prep_cmd(args)
        ed = {"date": d, "signals": [{"text": "Posters talked about the market.", "cites": [posts[0]["id"]]}],
              "posts": [{"id": posts[0]["id"]}]}
        (x / "days" / d / "edition.json").write_text(json.dumps(ed))
        xdaily.publish_cmd(args)

    scan(1, "2026-10-26T14:00:00Z")
    build()
    assert "2114705686513033399" not in (x / "days" / d / "prep.md").read_text()
    assert xdaily.status(d, pub)["next"]["type"] == "done"
    scan(2, "2026-10-26T17:00:00Z")  # the on-demand scan found one more post
    assert xdaily.status(d, pub)["next"]["command"] == f"sigma x prep {d}"
    build()
    assert xdaily.status(d, pub)["next"]["type"] == "done"
    assert json.loads((pub / "x/editions" / f"{d}.json").read_text())["window"][1] == "2026-10-26T17:00:00Z"


def test_the_x_dir_uses_the_data_root_unless_sigma_x_dir_is_set(monkeypatch, tmp_path):
    """Stated rule: the private X scan data is under the configured data root, or SIGMA_X_DIR when explicitly set."""
    from sigma import xdaily
    from sigma.paths import data_root

    monkeypatch.delenv("SIGMA_X_DIR")
    monkeypatch.setenv("SIGMA_DATA_ROOT", str(tmp_path / "inputs"))
    assert xdaily.x_dir() == data_root() / "x"
    monkeypatch.setenv("SIGMA_X_DIR", str(tmp_path / "elsewhere"))
    assert xdaily.x_dir() == tmp_path / "elsewhere"


def test_scan_check_warns_about_accounts_the_scan_missed_but_still_passes(monkeypatch, tmp_path, capsys):
    """stated-rule (skills/x-scan step 3: own posts and self-replies only; replies to others are dropped): a scan that is complete
    can still have an account with no posts, or one whose posts are all replies to others (the search matched the word `bot`,
    not the author). Counts here are worked by hand from the three accounts below."""
    from types import SimpleNamespace

    from sigma import xdaily

    monkeypatch.setenv("SIGMA_X_DIR", str(tmp_path))
    rows = [{"handle": h, "tier": "core", "type": "news"} for h in ("Active", "Quiet", "bot")]
    (tmp_path / "accounts.json").write_text(json.dumps({"accounts": rows}))
    monkeypatch.setattr(xdaily, "ACCOUNTS", tmp_path / "accounts.json")
    sd = tmp_path / "scan" / "2026-10-26"
    sd.mkdir(parents=True)
    base = {"created_at": "2026-10-26T13:08:00Z", "text": "x" * 50, "metrics": {}}
    posts = [{**base, "id": "2114705686513033360", "handle": "active"},
             {**base, "id": "2114705686513033361", "handle": "active", "in_reply_to_id": "2114705686513033360", "in_reply_to_handle": "active"},
             {**base, "id": "2114705686513033362", "handle": "bot", "in_reply_to_id": "2114705686513033399", "in_reply_to_handle": "someoneelse"}]
    (sd / "posts.jsonl").write_text("\n".join(json.dumps(p) for p in posts) + "\n")
    (sd / "quoted.jsonl").write_text("")
    (sd / "manifest.json").write_text(json.dumps({"date": "2026-10-26", "window_start": "2026-10-25T14:00:00Z",
        "window_end": "2026-10-26T14:00:00Z", "accounts_requested": 2, "accounts_ok": 2, "accounts_failed": [], "calls": 1,
        "rate_limited": False, "complete": True, "scanner": "test", "tool": "test", "contract_version": xdaily.contract_version()}))
    xdaily.scan_check_cmd(SimpleNamespace(date="2026-10-26"))  # raises SystemExit on a problem; warnings do not
    out = capsys.readouterr().out
    assert "requested 2 accounts; x-accounts.json lists 3" in out
    assert "1 of 3 core accounts have no post in the window: @quiet" in out
    assert "@bot: all 1 posts are replies to other people" in out
    assert "@active" not in out and "scan 2026-10-26 ok: 3 posts" in out


def test_today_is_the_pacific_date_even_when_the_machine_clock_is_utc(monkeypatch):
    """stated-rule (AGENTS.md: Sigma dates everything in Pacific time): 02:30 UTC on Oct 28 is 19:30 PDT on Oct 27, hand-worked."""
    from datetime import datetime, timezone

    from sigma import xdaily

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 2, 30, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr(xdaily, "datetime", Clock)
    assert xdaily.today() == "2026-10-27"


def test_health_says_which_stage_went_quiet_from_the_x_dir_alone(monkeypatch, tmp_path):
    """stated-rule (the scan is nightly, the edition follows it): a stage with no signal for over the limit is stale, and a
    scan's own manifest counts as a signal, so the check works before the scanner ever writes a heartbeat. Hours worked by hand."""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from sigma import xdaily

    monkeypatch.setenv("SIGMA_X_DIR", str(tmp_path))
    now = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)
    assert len(xdaily.health(now)[1]) == 2  # nothing written yet: both stages report no heartbeat
    sd = tmp_path / "scan" / "2026-10-27"
    sd.mkdir(parents=True)
    (sd / "manifest.json").write_text(json.dumps({"window_end": "2026-10-28T04:00:00Z"}))  # 8 h ago
    xdaily.heartbeat_cmd(SimpleNamespace(stage="edition", by="editor", date="2026-10-27"))
    hb = tmp_path / "heartbeat" / "edition.json"
    hb.write_text(json.dumps({**json.loads(hb.read_text()), "at": "2026-10-27T08:00:00Z"}))  # 28 h ago
    lines, probs = xdaily.health(now)
    assert len(probs) == 1 and probs[0].startswith("edition: nothing for 28 h") and lines[0].startswith("scan: last signal 8.0 h ago")
    assert xdaily.health(now, max_hours=30)[1] == []
