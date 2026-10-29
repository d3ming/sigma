"""The Alpha pages: /alpha/, one page per day, the JSON files agents read, the Research placeholder, the collapsible Alpha panel on
the home page, and the Alpha view that /x/ and its day pages open with.

The podcast home stays at `/`. When `published/alpha/` has a day, the home page gets the Alpha panel beside the podcast picks (a
collapsible side panel on a wide screen, a collapsible section above them on a phone). The data is built by `wire alpha-index` (see alpha_index.py); this module only reads it. Standard library only,
because the Vercel build has no packages."""
from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from . import alpha_sentiment, site
from .site import esc, human_date, mlink, ml, mt, absu, page, doc, plural, fmt_ts, safe_url

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "alpha-index.schema.json"
ALPHA_NAME, RESEARCH_PATH = "Alpha", "/research/"
MIN_PICKS, MAX_PICKS = 3, 12
SUMMARY = ("Every day's market calls from the people who move markets: who said it, how strongly, over what horizon, "
           "with a link to the post or the exact moment.")


def day_path(d: str) -> str:
    return f"/alpha/{d}/"


def load(published: Path) -> tuple[dict, dict]:
    """({date: day file}, index file). Only days with a valid-looking file count; a broken file is skipped, not fatal."""
    days = {}
    for f in sorted((published / "alpha").glob("????-??-??.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(d, dict) and d.get("date") == f.stem and isinstance(d.get("signals"), list):
            days[f.stem] = d
    idx = {}
    try:
        idx = json.loads((published / "alpha" / "index.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return days, idx


# ---------------------------------------------------------------- picks

def is_market(s: dict) -> bool:
    return str(s["ticker"]).startswith("@")


def groups(day: dict) -> list[dict]:
    """The day's stock signals grouped by (ticker, direction), strongest first. A group is higher confidence when two or more
    different speakers agree and one is a primary source, or one primary source states it strongly (stance 2). Anything else,
    one voice or a mild lean is labelled lower confidence."""
    g = defaultdict(list)
    for s in day["signals"]:
        if not is_market(s):
            g[(s["ticker"], s["direction"])].append(s)
    out = []
    for (t, dr), sigs in g.items():
        who = {s["speaker"] for s in sigs}
        prim = [s for s in sigs if s["origin"] == "primary"]
        top = max(abs(s["stance"]) for s in sigs)
        strong = bool(prim) and (len(who) >= 2 or top >= 2)
        score = sum(abs(s["stance"]) * (1.0 if s["origin"] == "primary" else 0.5) for s in sigs) + 0.1 * len(who)
        against = sum(1 for s in day["signals"] if s["ticker"] == t and s["direction"] != dr)
        out.append({"ticker": t, "direction": dr, "target": sigs[0].get("target") or t, "signals": sorted(
            sigs, key=lambda s: (-abs(s["stance"]), s["origin"] != "primary", s["speaker"])), "speakers": len(who),
            "primary": len(prim), "top": top, "lower": not strong, "score": score, "against": against})
    out.sort(key=lambda x: (-x["score"], x["ticker"]))
    return out


def picks(day: dict) -> list[dict]:
    """All higher-confidence groups (at most MAX_PICKS), topped up with the best lower-confidence ones to MIN_PICKS."""
    gs = groups(day)
    high = [x for x in gs if not x["lower"]][:MAX_PICKS]
    low = [x for x in gs if x["lower"]]
    return (high + low[:max(0, MIN_PICKS - len(high))])[:MAX_PICKS]


# What a market line is called and what its bullish and bearish counts mean, in plain words. Rates read bullish when lower rates are expected.
MARKET_WORDS = {"@MARKET": ("US stocks", "bullish", "bearish"), "@RATES": ("Interest rates", "expect lower rates", "expect higher rates"),
                "@CREDIT": ("Credit spreads", "bullish", "bearish")}


def market_label(m: dict) -> str:
    return MARKET_WORDS.get(m["ticker"], (m["target"],))[0]


def x_only(day: dict) -> dict:
    """The day with only its X signals: what the X panel and ticker tape show. Podcast signals stay on /alpha/ and in the JSON."""
    return dict(day, signals=[s for s in day["signals"] if s.get("source_kind") == "x"])


def sentiment_rows(day: dict, market_: bool = False) -> list[dict]:
    """The day's X sentiment per ticker (or per market target), best rank first: the file's own rows, or, for a day file written
    before they existed, the same rule applied to its X signals."""
    key = "markets" if market_ else "tickers"
    return day[key] if isinstance(day.get(key), list) else alpha_sentiment.aggregate(day["signals"], market=market_)


def sent_id(r: dict) -> str:
    return f"s-{r['ticker'].lstrip('@')}"


def sent_cls(r: dict) -> str:
    return alpha_sentiment.CLASS[r["label"]]


def sent_text(r: dict) -> str:
    return alpha_sentiment.badge(r)


RATES_WORDS = {"Strongly bullish": "Lower rates", "Bullish": "Lower rates", "Strongly bearish": "Higher rates", "Bearish": "Higher rates"}


def sent_head(r: dict) -> str:
    """Line 1 after the ticker: the arrow (hidden from a screen reader, the word says it), the label once, a muted tally. Rates read as
    what is expected of them: bullish is 'Lower rates'."""
    arrow, word = sent_text(r).split(" ", 1)
    if r["ticker"] == "@RATES":
        word = RATES_WORDS.get(r["label"], word)
    return (f'<span class="dir {sent_cls(r)}"><i aria-hidden="true">{esc(arrow)}</i> {esc(word)}</span> '
            f'<span class="tl">· {esc(alpha_sentiment.tally(r))}</span>')


# ---------------------------------------------------------------- pages

CSS = """
.alpha-day{margin:var(--space-4) 0 var(--space-6)}
.sig li{margin:0 0 .6em}
.banner{border:var(--line-1) solid var(--alpha);border-radius:var(--radius-sm);padding:var(--space-2) var(--space-3);margin:var(--space-3) 0}
.dayscroll{columns:3 9em;list-style:none;padding:0}
hr.lead{border:0;border-top:var(--line-1) solid var(--border);margin:var(--space-6) 0}
h1.lead{margin-top:var(--space-4)}
.duo-side{margin:0 0 var(--space-5)}
.alpha-panel{border:var(--line-1) solid var(--border);border-radius:var(--radius-sm);background:var(--surface-2)}
.alpha-panel>summary{cursor:pointer;list-style:none;display:flex;align-items:center;gap:var(--space-3);min-height:44px;padding:0 var(--space-4);border-radius:var(--radius-sm)}
.alpha-panel>summary::-webkit-details-marker{display:none}
.alpha-panel>summary::after{content:"";width:.5em;height:.5em;border:solid var(--text-muted);border-width:0 2px 2px 0;transform:rotate(-45deg);margin-left:auto;flex:none;transition:transform .15s}
.alpha-panel[open]>summary::after{transform:rotate(45deg)}
.alpha-panel>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.ap-x{display:inline-flex;flex:none;color:var(--text)}.xlogo{width:1.05em;height:1.05em}
.ap-title{font-weight:600}
.ap-sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.tape{display:none;flex:1;min-width:0;overflow:hidden;-webkit-mask-image:linear-gradient(90deg,transparent,#000 20px,#000 calc(100% - 20px),transparent);mask-image:linear-gradient(90deg,transparent,#000 20px,#000 calc(100% - 20px),transparent)}
.alpha-panel:not([open]) .tape{display:block}
.alpha-panel:not([open]) .ap-title{display:none}
.tape-run{display:flex;width:max-content;animation:tape var(--dur,40s) linear infinite}
.tape-seq{display:flex;flex:none;gap:var(--space-5);padding-right:var(--space-5)}
.tk-i{white-space:nowrap;font:400 var(--text-detail) var(--font-mono)}
.tk{color:var(--text);text-decoration:none;display:inline-block;padding:var(--space-3) 0}
.tk:hover,.tk:focus-visible{text-decoration:underline}.tk:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.tk b,.tk{font-weight:500}.tk-w{color:var(--text-muted);font-weight:400}
.ar{font-style:normal}.ar.pos,.dir.pos{color:var(--positive)}.ar.neg,.dir.neg{color:var(--negative)}.ar.neu,.dir.neu{color:var(--text-muted)}.ar.mix,.dir.mix{color:var(--alpha)}
.cards{margin:var(--space-2) 0 var(--space-4)}
.card{border-bottom:var(--line-1) solid var(--border)}
.card>summary{list-style:none;cursor:pointer;display:block;position:relative;min-height:44px;padding:var(--space-2) 1.6em var(--space-2) 0;line-height:1.35}
.card>summary::-webkit-details-marker{display:none}
.card>summary::after{content:"";position:absolute;right:.4em;top:1.15em;width:.45em;height:.45em;border:solid var(--text-muted);border-width:0 2px 2px 0;transform:rotate(-45deg);transition:transform .15s}
.card[open]>summary::after{transform:rotate(45deg)}
.card>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.card .c1{display:flex;flex-wrap:wrap;align-items:baseline;gap:.15em .5em}
.card .why{display:block;font-size:.92em;margin-top:.15em}
.card .tl{color:var(--text-muted);font-variant-numeric:tabular-nums}
.card .dir i{font-style:normal}.dir.pos{color:var(--positive)}.dir.neg{color:var(--negative)}
.card .lc{color:var(--text-muted);font-size:.7em;line-height:1;cursor:help}
.posts{list-style:none;padding:0 0 0 var(--space-3);margin:0 0 var(--space-3);border-left:var(--line-1) solid var(--border)}.posts li{margin:0 0 .35em;font-size:.92em}
.posts .st{font:600 .85em var(--font-mono);margin-right:.3em}.posts .st.pos{color:var(--positive)}.posts .st.neg{color:var(--negative)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.pods{margin:0 0 var(--space-3) var(--space-3);font-size:.88em}
.embeds{visibility:hidden;height:0;overflow:hidden;max-width:min(550px,100%);margin:0 0 var(--space-3) var(--space-3)}
.card.emb .embeds{visibility:visible;height:auto;overflow-x:clip;overflow-y:visible}.card.emb>.posts{display:none}
.embeds .twitter-tweet{margin:0 0 var(--space-3)!important;max-width:100%!important}.embeds .tw-later{display:none}
.embeds blockquote{overflow-wrap:anywhere}
.tw-more{margin:0 0 var(--space-3) var(--space-3);min-height:44px;padding:0 var(--space-4);font:500 var(--text-detail) var(--font-mono);color:var(--accent);background:none;border:var(--line-1) solid var(--border);border-radius:var(--radius-md);cursor:pointer}
.tw-more:hover{border-color:var(--accent)}.tw-more:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:600px){.embeds,.pods,.tw-more{margin-left:0}.card>.posts{padding-left:var(--space-2)}}
.card>.meta{margin:0 0 var(--space-3) var(--space-3)}
.rest{margin-top:0}.rest>summary{cursor:pointer;min-height:44px;display:flex;align-items:center;font:500 var(--text-detail) var(--font-mono);letter-spacing:.04em}
.rest>summary{list-style:none;gap:.6em}.rest>summary::-webkit-details-marker{display:none}
.rest>summary::before{content:"";width:.45em;height:.45em;border:solid var(--text-muted);border-width:0 2px 2px 0;transform:rotate(-45deg);transition:transform .15s;flex:none}
.rest[open]>summary::before{transform:rotate(45deg)}
.rest>summary:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
.rest-link a{display:inline-flex;align-items:center;min-height:44px;font:500 var(--text-detail) var(--font-mono);letter-spacing:.04em}
.rest-state{margin:var(--space-2) 0 var(--space-4);color:var(--text-muted);font-size:var(--text-detail)}
.rest-state[hidden]{display:none}
.rest-state.busy::before{content:"";display:inline-block;width:.9em;height:.9em;margin-right:.5em;vertical-align:-.12em;border:2px solid var(--border);border-top-color:var(--text-muted);border-radius:50%;animation:restspin .8s linear infinite}
@keyframes restspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.rest-state.busy::before{animation:none}}
.ap-h{font-size:var(--text-detail);margin:var(--space-3) 0 0;color:var(--text-muted);font-weight:500}
@keyframes tape{to{transform:translateX(calc(-100% / var(--n,2)))}}
.tape:hover .tape-run,.tape:focus-within .tape-run,.alpha-panel>summary:focus-visible .tape-run{animation-play-state:paused}
@media (prefers-reduced-motion:reduce){.tape{overflow-x:auto;-webkit-mask-image:none;mask-image:none}.tape-run{animation:none}.tape-seq[aria-hidden]{display:none}}
.ap-body{padding:0 var(--space-4) var(--space-3)}
.ap-more{margin:.4em 0}.ap-more a{text-decoration:underline;text-underline-offset:.2em}
.duo-main{min-width:0}
@media (min-width:1000px){
body:has(.duo) .wrap{max-width:1180px}
.duo{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:var(--space-6);align-items:start}
.duo:has(.alpha-panel:not([open])){grid-template-columns:minmax(0,1fr);row-gap:var(--space-4)}
.duo-side{grid-column:2;grid-row:1;position:sticky;top:var(--space-4);max-height:calc(100vh - 2 * var(--space-4));overflow:auto;margin:0}
.duo:has(.alpha-panel:not([open])) .duo-side{grid-column:1;position:static;max-height:none;overflow:visible}
.duo-main{grid-column:1;grid-row:1}
.duo:has(.alpha-panel:not([open])) .duo-main{grid-row:2}
}
"""


def banner(day: dict) -> str:
    if day.get("complete"):
        return ""
    miss = "; ".join(f'{m.get("source", "?")}: {m.get("reason", "")}' for m in day.get("missing", []))
    return f'<p class="banner"><b>Incomplete day.</b> Some sources are not in yet ({esc(miss)}). Counts can still change.</p>'


def pick_tickers(day: dict) -> list[str]:
    """The tickers of the day's picks (one card per ticker, strongest first), whichever direction made them a pick."""
    out: list[str] = []
    for x in picks(day):
        if x["ticker"] not in out:
            out.append(x["ticker"])
    return out


def ticker_rows(day: dict, market_: bool = False) -> dict[str, dict]:
    """ticker -> its aggregate row: the day's X row, or, for a ticker only a podcast spoke about, the same rule over that ticker's signals."""
    rows = {r["ticker"]: r for r in sentiment_rows(day, market_)}
    by = defaultdict(list)
    for s in day["signals"]:
        if is_market(s) == market_ and s["ticker"] not in rows:
            by[s["ticker"]].append(s)
    for t, ss in by.items():
        rows[t] = alpha_sentiment.row(t, ss[0].get("target") or t, ss, 0)
    return rows


def day_posts(day: dict, ticker: str) -> list[dict]:
    """Every signal of the day about `ticker`, firmest first: first-hand before recap, then by stance."""
    return sorted((s for s in day["signals"] if s["ticker"] == ticker),
                  key=lambda s: (s["origin"] != "primary", -abs(s["stance"]), s["speaker"], s["id"]))


TWEET = re.compile(r"^https?://(?:www\.)?(?:x|twitter)\.com/(\w+)/status/(\d+)", re.I)
EMBED_MAX = 10


def arrows(st: int) -> str:
    return ("▲" if st > 0 else "▼") * (2 if abs(st) >= 2 else 1)


def post_md(s: dict) -> str:
    link = safe_url(s.get("link"))
    note = [s["source_name"] or "podcast"] if s.get("source_kind") == "podcast" else []
    return (f"- {ml(s['speaker'])} ({s['stance']:+d}): {mt(s['reason'])}" + (f" ({mt(', '.join(note))})" if note else "")
            + (f" [post]({link})" if link else ""))


def body_html(sigs: list[dict]) -> str:
    """What a card opens to: X's own embed for each X post (a blockquote holding only the link, so no post text is copied here; the page
    script loads widgets.js on the first open), a plain list of who said it and which way as the fallback when the embed or the script is
    not there, and one compact line for podcast signals. The first EMBED_MAX embeds show, the rest wait behind a 'Show N more' button."""
    seen, xs, pods = set(), [], []
    for s in sigs:
        link = safe_url(s.get("link"))
        if s.get("source_kind") == "podcast":
            pods.append(s)
        elif link not in seen:
            seen.add(link)
            xs.append((s, link, TWEET.match(link)))
    lis = "".join(f'<li><span class="st {"pos" if s["stance"] > 0 else "neg"}" aria-hidden="true">{arrows(s["stance"])}</span> '
                  f'<span class="sr">{"bullish" if s["stance"] > 0 else "bearish"}</span> '
                  + (f'<a href="{esc(link)}" rel="noopener noreferrer">{esc(s["speaker"])}</a>' if link else esc(s["speaker"])) + "</li>" for s, link, _ in xs)
    em = [(s, m) for s, _, m in xs if m]
    bq = lambda s, m, cls: (f'<blockquote class="{cls}" data-dnt="true" data-theme="light" data-conversation="none">'
                            f'<a href="https://twitter.com/{esc(m.group(1))}/status/{m.group(2)}">{esc(s["speaker"])}</a></blockquote>')
    first = "".join(bq(s, m, "twitter-tweet") for s, m in em[:EMBED_MAX])
    later = "".join(bq(s, m, "tw-later") for s, m in em[EMBED_MAX:])
    more = f'<button type="button" class="tw-more" hidden>Show {len(em) - EMBED_MAX} more</button>' if later else ""
    out = f'<ul class="posts">{lis}</ul>' if lis else ""
    if em:
        out += f'<div class="embeds">{first}{later}</div>{more}'
    if pods:
        out += '<p class="meta pods">' + " · ".join(
            (f'<a href="{esc(safe_url(s.get("link")))}" rel="noopener noreferrer">' if safe_url(s.get("link")) else "<span>")
            + f'{arrows(s["stance"])} {esc(s["speaker"])}, {esc(s["source_name"] or "podcast")}' + ("</a>" if safe_url(s.get("link")) else "</span>") for s in pods) + "</p>"
    return out


def card(r: dict, sigs: list[dict], ident: str = "", name: str = "", extra: str = "") -> str:
    """The one card design (home panel, /alpha/, /x/): collapsed it is 'TICKER ▲ Bullish · 3/3' over a line of what was said; opened it
    shows the posts behind it as X embeds. A native <details>, so it works on a phone and without a script. Low confidence is a small dim dot after the tally, never a faded card."""
    why = f'<span class="why">{esc(r["reason"])}</span>' if r.get("reason") else ""
    lo = (' <span class="lc" role="img" aria-label="low confidence" title="Low confidence: one voice or a mild lean">●</span>'
          if r.get("confidence") == "low" else "")
    return (f'<details class="card"{f" id={chr(34)}{esc(ident)}{chr(34)}" if ident else ""}><summary><span class="c1"><span class="chip">{esc(name or r["ticker"])}</span> '
            f'{sent_head(r)}{lo}</span>{why}</summary>{body_html(sigs)}{extra}</details>')


def cards_md(r: dict, sigs: list[dict], level: str, name: str = "") -> list[str]:
    head = f"{level} {mt(name or r['ticker'])}: {r['label']} {alpha_sentiment.tally(r)}"
    return [head, ""] + ([mt(r["reason"]), ""] if r.get("reason") else []) + [post_md(s) for s in sigs] + [""]


def rest_rows(day: dict, taken: set) -> list[dict]:
    """Rows of the tickers that are not picks, best first (the X ranking, then the podcast-only ones)."""
    rows = ticker_rows(day)
    return sorted((r for t, r in rows.items() if t not in taken), key=lambda r: (-r["rank"], -r["speakers"], r["ticker"]))


def market_order(day: dict) -> list[dict]:
    rows = ticker_rows(day, True)
    return sorted(rows.values(), key=lambda r: (-r["speakers"], r["ticker"]))


HASH_JS = ("<script>(()=>{const o=()=>{const e=document.getElementById(decodeURIComponent(location.hash.slice(1)));if(!e)return;"
           "for(let n=e;n;n=n.parentElement)if(n.tagName==='DETAILS')n.open=true;e.scrollIntoView()};addEventListener('hashchange',o);o()})()</script>")

EMBED_JS = ("<script>(()=>{const W='https://platform.twitter.com/widgets.js';let ld=null;const dark=()=>{const t=document.documentElement.dataset.theme;"
            "return t?t==='dark':matchMedia('(prefers-color-scheme: dark)').matches};"
            "const load=()=>ld||(ld=new Promise((ok,no)=>{const s=document.createElement('script');s.src=W;s.async=true;s.charset='utf-8';"
            "s.onload=()=>window.twttr&&twttr.ready?twttr.ready(ok):no();s.onerror=no;document.head.appendChild(s)}));"
            "const go=c=>{const e=c.querySelector('.embeds');if(!e||c.dataset.tw)return;c.dataset.tw='1';"
            "e.querySelectorAll('blockquote').forEach(b=>b.dataset.theme=dark()?'dark':'light');"
            "load().then(t=>{t.events.bind('rendered',ev=>{if(c.contains(ev.target))c.classList.add('emb')});t.widgets.load(c);"
            "const m=c.querySelector('.tw-more');if(m){m.hidden=false;m.onclick=()=>{e.querySelectorAll('.tw-later').forEach(b=>{b.dataset.theme=dark()?'dark':'light';"
            "b.className='twitter-tweet'});m.remove();t.widgets.load(c)}}}).catch(()=>{c.dataset.tw=''})};"
            "addEventListener('toggle',ev=>{const c=ev.target;if(c.classList&&c.classList.contains('card')&&c.open)go(c)},true);"
            "document.querySelectorAll('details.card[open]').forEach(go)})()</script>")


def rest_path(d: str) -> str:
    """The static fragment holding the cards of a day's 'More from today' (bare HTML, fetched after the page loads)."""
    return f"/alpha/{d}/rest.html"


def more_path(d: str) -> str:
    """The same cards as a page of their own: what the 'N more tickers' link opens without a script."""
    return f"/alpha/{d}/more/"


def rest_cards(day: dict) -> str:
    pt = set(pick_tickers(day))
    return "".join(card(r, day_posts(day, r["ticker"]), sent_id(r)) for r in rest_rows(day, pt))


def more_page(day: dict) -> str:
    d = day["date"]
    body = (f'<h1>{ALPHA_NAME}: more from today</h1><p class="meta">{esc(human_date(d, True))} · the tickers that are not in the daily picks. '
            f'<a href="{day_path(d)}">Back to the day</a></p><div class="cards">{rest_cards(day)}</div>{HASH_JS}{EMBED_JS}')
    return page(f"{ALPHA_NAME} · more from {human_date(d)} · {site.SITE}", body, "alpha", f"The rest of {human_date(d)}'s tickers.", md=site.md_of(day_path(d)), updated=d)


# 'More from today' is not in the page. The static link becomes a toggle (no script: the link stays and opens the same cards as a page). The
# fragment is fetched when the browser is idle, so opening it is usually instant; if it is not in yet, a loading line shows until it is. A
# link to a ticker inside it (#s-XYZ) opens it first.
REST_JS = ("<script>(()=>{const p=document.querySelector('p.rest-link[data-rest]');if(!p)return;const src=p.dataset.rest,n=p.dataset.n,label=p.textContent.trim();"
           "const d=document.createElement('details');d.className='rest';const sm=document.createElement('summary');sm.textContent=label;d.appendChild(sm);"
           "const st=document.createElement('p');st.className='rest-state';st.hidden=true;st.setAttribute('role','status');d.appendChild(st);"
           "const box=document.createElement('div');box.className='cards';d.appendChild(box);let pr=null,done=false;"
           "const get=()=>pr||(pr=fetch(src,{credentials:'same-origin'}).then(r=>{if(!r.ok)throw 0;return r.text()}).catch(e=>{pr=null;throw e}));"
           "const show=()=>{if(done)return Promise.resolve();if(d.open)st.className='rest-state busy',st.textContent='Loading '+label+'…',st.hidden=false;"
           "return get().then(h=>{if(done)return;done=true;box.innerHTML=h;st.hidden=true;if(location.hash)dispatchEvent(new Event('hashchange'))}).catch(()=>{"
           "st.className='rest-state';st.hidden=false;st.textContent='Could not load. ';const a=document.createElement('a');a.href=p.querySelector('a').href;a.textContent='Open them as a page';st.appendChild(a)})};"
           "d.addEventListener('toggle',()=>{if(d.open)show()});p.replaceWith(d);"
           "const idle=window.requestIdleCallback||(f=>setTimeout(f,300));idle(()=>{get().catch(()=>{})},{timeout:3000});"
           "const hs=()=>{const h=decodeURIComponent(location.hash.slice(1));if(h&&!done&&!document.getElementById(h)){d.open=true;show()}};addEventListener('hashchange',hs);hs()})()</script>")


def day_body(day: dict, days: list[str]) -> str:
    c = day.get("counts", {})
    pt = pick_tickers(day)
    rows = ticker_rows(day)
    mk = market_order(day)
    head = (f'<h1>{ALPHA_NAME}</h1><p class="lede">{esc(SUMMARY)} {esc(site.NOT_ADVICE)}</p>'
            f'<p class="meta">{esc(human_date(day["date"], True))} · {plural(c.get("signals", len(day["signals"])), "signal")} '
            f'· <a href="/alpha/{day["date"]}.json">this day as JSON</a> · '
            f'<a href="/alpha/index.json">all days</a> · <a href="/llms.txt">for agents</a></p>{banner(day)}')
    body = head + '<h2>Daily picks</h2>'
    body += (f'<p class="meta">Where the most sources point, strongest first. Open a card for the posts behind it. A small dot: one voice or a mild lean. '
             f'{esc(alpha_sentiment.TALLY_NOTE)}</p><div class="cards">{"".join(card(rows[t], day_posts(day, t), sent_id(rows[t])) for t in pt)}</div>'
             if pt else "<p>No stock signals yet today.</p>")
    if mk:
        body += '<h2>Markets</h2><div class="cards">' + "".join(card(r, day_posts(day, r["ticker"]), sent_id(r), market_label(r)) for r in mk) + "</div>"
    rest = rest_rows(day, set(pt))
    if rest:
        d = day["date"]
        body += (f'<h2>More from today</h2><p class="rest-link" data-rest="{rest_path(d)}" data-n="{len(rest)}">'
                 f'<a href="{more_path(d)}">{plural(len(rest), "more ticker")}</a></p>')
    older = [d for d in days if d != day["date"]]
    if older:
        body += '<h2>Earlier days</h2><ul class="dayscroll">' + "".join(
            f'<li><a href="{day_path(d)}">{esc(human_date(d))}</a></li>' for d in older) + '</ul>'
    body += (f'<p class="meta">Also: <a href="/">Podcasts</a> · <a href="{RESEARCH_PATH}">Research</a> · '
             f'<a href="/alpha/schema.json">JSON schema</a></p>{HASH_JS}{EMBED_JS}{REST_JS if rest else ""}')
    return body


def day_page(day: dict, days: list[str], home: bool) -> str:
    desc = f"{SUMMARY} {human_date(day['date'])}."
    title = f"{ALPHA_NAME} · {site.SITE}" if home else f"{ALPHA_NAME} · {human_date(day['date'])} · {site.SITE}"
    return page(title, day_body(day, days), "alpha", desc, md="/alpha.md" if home else site.md_of(day_path(day["date"])), updated=day["date"])


def day_md(day: dict, days: list[str], home: bool) -> str:
    c = day.get("counts", {})
    day_json = absu(f"/alpha/{day['date']}.json")
    out = [f"# Alpha, {human_date(day['date'], True)}" if not home else "# Wire: Alpha", "", "> " + SUMMARY, "", site.NOT_ADVICE, ""]
    out += [f"{plural(c.get('signals', len(day['signals'])), 'signal')}. "
            f"This day as JSON: [{day['date']}.json]({day_json}); all days: [index.json]({absu('/alpha/index.json')}); "
            f"schema: [schema.json]({absu('/alpha/schema.json')}); index of the whole site: [llms.txt]({absu('/llms.txt')}).", ""]
    if not day.get("complete"):
        out += ["**Incomplete day.** " + "; ".join(f"{mt(m.get('source'))}: {mt(m.get('reason'))}" for m in day.get("missing", [])), ""]
    pt, rows = pick_tickers(day), ticker_rows(day)
    out += ["## Daily picks", "", f"Where the most sources point, strongest first. {alpha_sentiment.TALLY_NOTE}", ""]
    for t in pt:
        out += cards_md(rows[t], day_posts(day, t), "###")
    if mk := market_order(day):
        out += ["## Markets", ""]
        for r in mk:
            out += cards_md(r, day_posts(day, r["ticker"]), "###", market_label(r))
    if rest := rest_rows(day, set(pt)):
        out += ["## More from today", ""]
        for r in rest:
            out += cards_md(r, day_posts(day, r["ticker"]), "###")
    older = [d for d in days if d != day["date"]]
    if older:
        out += ["## Earlier days", ""] + [f"- {mlink(d, absu(site.md_of(day_path(d))))}" for d in older] + [""]
    out += [f"More: [Podcasts]({absu('/index.md')}), [Research]({absu(site.md_of(RESEARCH_PATH))}).", ""]
    return doc(out)


def research_page() -> str:
    body = ('<h1>Research</h1><p class="lede">A few deep reports each week on how AI is changing the way software and other work gets made. '
            'The first reports are in preparation. They will sit apart from the daily Alpha.</p>'
            '<p class="meta">Nothing is published here yet. Everything on this site that is live today is under <a href="/">Alpha</a> '
            'and <a href="/">Podcasts</a>.</p>')
    return page(f"Research · {site.SITE}", body, "research", "Weekly deep reports on how AI changes the work, in preparation.", md=site.md_of(RESEARCH_PATH))


def research_md() -> str:
    return doc(["# Research", "", "> Weekly deep reports on how AI is changing the way work gets made. In preparation; nothing published yet.", "",
                f"Live today: [Alpha]({absu('/alpha.md')}), [Podcasts]({absu('/index.md')})."])


def llms_section(days: dict) -> list[str]:
    last = max(days)
    d = days[last]
    return ["## Alpha (start here for market questions)", "",
            f"- [Alpha today]({absu('/alpha.md')}): {plural(len(d['signals']), 'signal')} for {last}, daily picks first, each with speaker, role, "
            "origin (primary or recap), horizon in days and a link to the post or the moment",
            f"- [index.json]({absu('/alpha/index.json')}): every day, newest first, with its path, signal count and whether the day is complete",
            f"- [/alpha/YYYY-MM-DD.json]({absu(f'/alpha/{last}.json')}): one day's full signal list, validated by [schema.json]({absu('/alpha/schema.json')}). "
            "Each signal has a stable `id`, `ticker` (an @ ticker such as @MARKET is a market-wide view), `direction`, `stance` (±1 lean, ±2 strong), "
            "`origin`, `horizon_days`. Signals are what sources said, not advice",
            "- The same day file carries `tickers[]` (and `markets[]`): the day's X signals added up per ticker, one vote per speaker, with `label` "
            "(Strongly bearish, Bearish, Neutral, Bullish, Strongly bullish, or Mixed), `net`, `bull`/`bear`/`neutral` speaker counts, `agreement`, "
            "`dispersion`, `confidence` and a one-line `reason`. The Sentiment page shows it as its X column",
            f"- [Research]({absu(site.md_of(RESEARCH_PATH))}): weekly deep reports, in preparation", ""]


def lead(days: dict, date: str) -> tuple[str, str]:
    """The Alpha view a /x/ page opens with: that date's Alpha day as (HTML, Markdown), or ("", "") when it has none."""
    if date not in days:
        return "", ""
    order = sorted(days, reverse=True)
    return (day_body(days[date], order).replace("<h1>", '<h1 class="lead">', 1) + '<hr class="lead">',
            day_md(days[date], order, False) + "\n---\n\n")


PANEL_JS = """<script>(()=>{const d=document.getElementById('alpha-panel');if(!d)return;const K='wire-alpha-panel';let v=null;
try{v=localStorage.getItem(K)}catch(e){}
d.open=v==='open'||v==='closed'?v==='open':matchMedia('(min-width:1000px)').matches;
d.querySelector('summary').addEventListener('click',()=>setTimeout(()=>{try{localStorage.setItem(K,d.open?'open':'closed')}catch(e){}}))})()</script>"""

# The official X mark, one colour (currentColor).
X_LOGO = ('<svg class="xlogo" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 '
          '8.502 11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>')


def tape_items(d: dict) -> list[tuple[str, str, str, str, str, str]]:
    """What the ticker tape scrolls, and nothing else: (ticker, arrow class, arrow, words for a screen reader, link, label) for each
    ticker with a lean or a split, ranked by speakers x |net| with Mixed ones kept in (alpha_sentiment.tape_rows)."""
    return [(r["ticker"], sent_cls(r), alpha_sentiment.badge(r).split(" ")[0],
             r["label"].lower(), f'/alpha/{d["date"]}/#{sent_id(r)}', r["label"].split()[-1].capitalize())
            for r in alpha_sentiment.tape_rows(sentiment_rows(d))]


def tape_html(d: dict) -> str:
    """A CSS-only ticker tape inside the panel's summary: the items repeated in equal runs, slid left by one run's width so the loop is
    seamless. It scrolls the per-ticker items only (`NVDA ▲ Bullish`, `MU ◆ Mixed`); no date, count or summary. Only the first run is
    read out; the repeats are aria-hidden and out of the tab order. It pauses on hover and focus."""
    items = tape_items(d)
    if not items:
        return ""

    def run(first: bool) -> str:
        att = "" if first else ' aria-hidden="true"'
        tab = "" if first else ' tabindex="-1"'
        lis = "".join(
            f'<span class="tk-i"{" role=" + chr(34) + "listitem" + chr(34) if first else ""}><a class="tk" href="{esc(h)}"{tab}>{esc(t)} '
            f'<i class="ar {k}" aria-hidden="true">{a}</i><span class="ap-sr">{w}</span> <span class="tk-w">{esc(lab)}</span></a></span>'
            for t, k, a, w, h, lab in items)
        lab = f' role="list" aria-label="Today\'s X signals by ticker, scrolling"' if first else ""
        return f'<span class="tape-seq"{lab}{att}>{lis}</span>'

    chars = sum(len(t) + len(lab) + 5 for t, _, _, _, _, lab in items)
    seq_px = chars * 8.5 + len(items) * 28  # a run's width, roughly (monospace, gaps)
    n = max(2, -(-1700 // int(seq_px)))
    return (f'<span class="tape" style="--n:{n};--dur:{max(20, round(seq_px / 40))}s"><span class="tape-run">'
            + run(True) + "".join(run(False) for _ in range(n - 1)) + "</span></span>")


def panel(days: dict) -> str:
    """The home page's X panel: native <details>, so it opens and closes without a script. Open, it is the list of the day's top X
    signals; collapsed, its summary is a scrolling ticker tape of the same. It only holds X signals (source_kind x): podcast signals
    stay on /alpha/. It is rendered open; the script right after it (before the page paints, so nothing shifts) closes it on a phone
    unless the reader chose otherwise, and keeps the choice in localStorage."""
    if not days:
        return ""
    d = x_only(days[max(days)])
    if not d["signals"]:
        return ""
    rows_all = alpha_sentiment.tape_rows(sentiment_rows(d), 6, 2)
    top = ", ".join(r["ticker"] for r in rows_all[:3])
    short = human_date(d["date"]).rsplit(",", 1)[0]
    one = f"{short} · {plural(len(d['signals']), 'X signal')}"
    link = lambda r: f'<p class="meta"><a href="/alpha/{d["date"]}/#{esc(sent_id(r))}">On the day page</a></p>'
    rows = "".join(card(r, day_posts(d, r["ticker"]), extra=link(r)) for r in rows_all)
    mrows = sorted(ticker_rows(d, True).values(), key=lambda r: (-r["speakers"], r["ticker"]))[:3]
    mline = ('<h3 class="ap-h">Markets</h3><div class="cards">' + "".join(card(r, day_posts(d, r["ticker"]), name=market_label(r), extra=link(r)) for r in mrows) + "</div>") if mrows else ""
    warn = '<p class="meta">Incomplete day: some sources are not in yet.</p>' if not days[max(days)].get("complete") else ""
    return (f'<details class="alpha-panel" id="alpha-panel" open><summary><span class="ap-x" role="img" aria-label="X signals">{X_LOGO}</span>'
            f'<span class="ap-title">X signals</span>'
            f'<span class="ap-sr">{esc(one)}{esc(" · top: " + top if top else "")}. Open or close the panel.</span>{tape_html(d)}</summary>'
            f'<div class="ap-body"><p class="meta">{esc(human_date(d["date"], True))}</p>{warn}'
            f'<div class="cards">{rows}</div>{mline}'
            f'<p class="ap-more"><a href="/alpha/">All of today\'s Alpha</a> (X and podcasts) · <a href="/alpha/{d["date"]}.json">JSON</a></p>'
            f'<p class="meta">{esc(site.NOT_ADVICE)}</p></div></details>{PANEL_JS}{EMBED_JS}')


def build(published: Path, out: Path, emit, sm: list, newest: str) -> bool:
    """Write the Alpha pages and files; return False (writing nothing) when there is no data, so the site stays as it was."""
    days, _ = load(published)
    if not days:
        return False
    order = sorted(days, reverse=True)
    for d in order:
        emit(day_path(d), day_page(days[d], order, False), day_md(days[d], order, False), d)
        site.write(out / "alpha" / f"{d}.json", json.dumps(days[d], indent=1, ensure_ascii=False) + "\n")
        sm.append((f"/alpha/{d}.json", d))
        if rest_rows(days[d], set(pick_tickers(days[d]))):  # the fragment the day page fetches, and its no-script page (not in the sitemap)
            site.write(out / "alpha" / d / "rest.html", rest_cards(days[d]) + "\n")
            site.write(out / site.file_of(more_path(d)), more_page(days[d]))
    emit("/alpha/", day_page(days[order[0]], order, True), day_md(days[order[0]], order, True), order[0])
    rows = [{"date": d, "path": f"/alpha/{d}.json", "url": absu(f"/alpha/{d}.json"), "page": absu(day_path(d)), "signals": len(days[d]["signals"]),
             "complete": bool(days[d].get("complete")), "generated_at": days[d].get("generated_at")} for d in order]
    site.write(out / "alpha" / "index.json", json.dumps({"schema_version": 1, "base_url": site.BASE_URL, "schema": absu("/alpha/schema.json"),
               "about": "One file per day with every Alpha signal. Newest first.", "days": rows}, indent=1, ensure_ascii=False) + "\n")
    sm.append(("/alpha/index.json", order[0]))
    if SCHEMA.exists():
        site.write(out / "alpha" / "schema.json", SCHEMA.read_text(encoding="utf-8"))
        sm.append(("/alpha/schema.json", order[0]))
    emit(RESEARCH_PATH, research_page(), research_md(), newest)
    return True
