"""Build static pages from checked publication data without reading transcripts."""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import unicodedata
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, unquote

from . import board, claimdedupe, creators, stance
from . import entities as ents
from .creators import norm_show
from .tickers import normalize as norm_ticker
from . import signals_sentiment
from .publication_policy import MIN_SCORE
from . import research as public_research
from .paths import data_root
from .site_config import load as load_site_identity

ROOT = Path(__file__).resolve().parent.parent
NOT_ADVICE = "What the sources lean toward, not investment advice."
X_PROFILE = ""
X_LOGO = ('<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M18.244 2.25h3.308l-7.227 8.26 8.502 '
          '11.24H16.17l-5.214-6.817L4.99 21.75H1.68l7.73-8.835L1.254 2.25H8.08l4.713 6.231zm-1.161 17.52h1.833L7.084 4.126H5.117z"/></svg>')
MAKER = ""
BASE_URL = "https://example.invalid"
SITE = "Sigma"
TOKENS = ROOT / "web" / "tokens.css"  # the shared visual base (see web/WEB_DESIGN.md); the build puts it in front of CSS in style.css
ASSETS = ROOT / "site-assets"  # favicon.svg, favicon.ico, apple-touch-icon.png, icon-192.png: copied to the site root
ICONS = ('<link rel="icon" href="/favicon.svg" type="image/svg+xml"><link rel="icon" href="/favicon.ico" sizes="48x48">'
         '<link rel="apple-touch-icon" href="/apple-touch-icon.png"><meta name="theme-color" content="#080a11">')
CREATORS_FILE = data_root() / "creators.json"
SOURCES_FILE = data_root() / "sources.yaml"
ENTITIES_FILE = data_root() / "entities.json"
FONTS = ("https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600&family=Geist+Mono:wght@400;500;600"
         "&family=Unbounded:wght@500;600&display=swap")
MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

CSS = """\
/* Sigma: a signal board. Colors, fonts, type, spacing, radii and line weights come from web/tokens.css (prepended at build);
   this file is Sigma's own layout and components, and the lens and platform hues that only Sigma uses. */
:root{--signals:light-dark(#b7740c,#f2b84b);--on-signals:light-dark(#fff,#1a1204);--yt:light-dark(#d4102b,#ff5a6e);--ap:light-dark(#8f3fd1,#c58cf5);--sp:light-dark(#12843c,#3ddc84)}
@supports not (color:light-dark(#000,#fff)){:root{--signals:#b7740c;--on-signals:#fff;--yt:#d4102b;--ap:#8f3fd1;--sp:#12843c}@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--signals:#f2b84b;--on-signals:#1a1204;--yt:#ff5a6e;--ap:#c58cf5;--sp:#3ddc84}}:root[data-theme="dark"]{--signals:#f2b84b;--on-signals:#1a1204;--yt:#ff5a6e;--ap:#c58cf5;--sp:#3ddc84}}
*{box-sizing:border-box}
[hidden]{display:none!important}
html{-webkit-text-size-adjust:100%;background:var(--base)}
body{position:relative;isolation:isolate;margin:0;background:var(--base);color:var(--text);font:16px/1.6 var(--font-sans);overflow-x:hidden}
body::before{content:"";position:absolute;inset:0 0 auto;height:640px;z-index:-1;pointer-events:none;
background:radial-gradient(720px 260px at 50% -40px,var(--glow),transparent),radial-gradient(var(--grid) 1.2px,transparent 1.7px) 0 0/24px 24px;
-webkit-mask-image:linear-gradient(#000 30%,transparent);mask-image:linear-gradient(#000 30%,transparent)}
.wrap{max-width:760px;margin:0 auto;padding:0 20px}
header.site{padding:22px 0 0;border-top:var(--line-2) solid transparent;border-image:linear-gradient(90deg,var(--accent),transparent 55%) 1}
header.site .wrap{display:flex;align-items:center;justify-content:space-between;gap:var(--space-4)}
.id{display:flex;align-items:baseline;gap:var(--space-3)}
.maker{display:inline-flex;align-items:center;gap:5px;font:500 11.5px var(--font-mono);letter-spacing:.04em;color:var(--text-muted);text-decoration:none}
.maker svg{width:11px;height:11px;display:block}
.maker:hover{color:var(--accent)}
.brand{display:inline-flex;align-items:center;gap:11px;font:600 1.3rem/1 var(--font-display);letter-spacing:-.01em;color:var(--text);text-decoration:none}
.brand::before{content:"";width:24px;height:24px;background:url("__MARK__") center/contain no-repeat}
.bar{display:flex;align-items:center;gap:18px}
nav{display:flex;flex-wrap:wrap;gap:6px 14px}
nav a{font:500 var(--text-caption) var(--font-mono);color:var(--text-muted);text-decoration:none;letter-spacing:.06em;text-transform:uppercase}
nav a:hover,nav a[aria-current]{color:var(--accent)}
@media(max-width:600px){header.site .wrap{flex-wrap:wrap;gap:var(--space-4)}.bar{width:100%;justify-content:space-between;gap:var(--space-3)}nav{flex-wrap:nowrap;gap:var(--space-4)}}
.theme-switch{position:relative;display:inline-flex}
.theme-switch summary{display:inline-flex;align-items:center;justify-content:center;width:30px;height:28px;color:var(--text-muted);border:var(--line-1) solid var(--border);border-radius:var(--radius-md);cursor:pointer;list-style:none}
.theme-switch summary::-webkit-details-marker{display:none}
.theme-switch summary svg{width:16px;height:16px;display:block}
.theme-switch summary:hover,.theme-switch[open] summary{color:var(--accent)}
.theme-switch summary:focus-visible{outline:var(--line-2) solid var(--accent);outline-offset:2px}
.theme-switch-popover{position:absolute;top:calc(100% + 8px);right:0;z-index:30;min-width:148px;margin:0;padding:var(--space-1);background:var(--surface-2);border:var(--line-1) solid var(--border);border-radius:var(--radius-md);box-shadow:0 8px 24px rgb(0 0 0/.18)}
.theme-switch-popover button{display:flex;align-items:center;gap:var(--space-3);width:100%;min-height:40px;padding:0 var(--space-3);color:var(--text-muted);background:none;border:0;border-radius:var(--radius-md);font:500 var(--text-caption) var(--font-mono);text-align:left;cursor:pointer}
.theme-switch-popover button svg{width:16px;height:16px}
.theme-switch-popover button:hover{background:var(--surface-3);color:var(--text)}
.theme-switch-popover button[aria-pressed=true]{color:var(--text);font-weight:600}
.theme-switch-popover button[aria-pressed=true] svg{color:var(--accent)}
main{padding:56px 0 80px}
h1{font:500 var(--text-title)/1.2 var(--font-display);letter-spacing:-.01em;margin:0 0 .6em;text-wrap:balance}
h2{display:flex;align-items:center;gap:var(--space-3);font:500 var(--text-caption) var(--font-mono);letter-spacing:.14em;text-transform:uppercase;color:var(--text-muted);margin:3.4em 0 1.1em}
h2::before{content:"";width:6px;height:6px;background:var(--accent);flex:none}
h2::after{content:"";flex:1;height:1px;background:var(--border)}
p{margin:.6em 0}
a{color:inherit;text-decoration-color:var(--border);text-underline-offset:4px;text-decoration-thickness:1px}
a:hover{color:var(--accent);text-decoration-color:var(--accent)}
a:focus-visible,button:focus-visible{outline:var(--line-2) solid var(--accent);outline-offset:3px;border-radius:var(--radius-xs)}
.date{font:500 var(--text-caption) var(--font-mono);letter-spacing:.12em;text-transform:uppercase;color:var(--accent);margin:0 0 .6em}
.entry{display:grid;grid-template-columns:2.6rem 1fr;padding:28px 0;border-top:var(--line-1) solid var(--border)}
.n{font:500 var(--text-caption)/2.6 var(--font-mono);color:var(--text-muted);font-variant-numeric:tabular-nums}
.entry h3{font:600 var(--text-heading)/1.28 var(--font-sans);letter-spacing:-.02em;margin:0;text-wrap:balance}
.entry h3 a{text-decoration:none}
.meta{font:400 var(--text-detail) var(--font-mono);color:var(--text-muted);margin:.5em 0 0}
.listen{display:inline-flex;gap:0;margin-left:6px;vertical-align:middle}
.lk{display:inline-flex;align-items:center;justify-content:center;width:32px;height:32px;margin:-8px 0;color:var(--brand);border-radius:var(--radius-md);opacity:.85}
.lk svg{width:20px;height:20px;fill:currentColor;display:block}
.lk .cut{fill:none;stroke:var(--base);stroke-width:1.9;stroke-linecap:round}
.lk .ln{fill:none;stroke:currentColor;stroke-width:1.7;stroke-linecap:round}
.lk:hover,.lk:focus-visible{opacity:1;background:var(--surface-2)}
.lk.tx{--brand:var(--text-muted)}.lk.yt{--brand:var(--yt)}.lk.ap{--brand:var(--ap)}.lk.sp{--brand:var(--sp)}
.take{color:var(--text-muted);margin:.8em 0 0;font-size:.98rem;max-width:62ch}
.claims{list-style:none;padding:0;margin:1.1em 0 0}
.claims li{padding:.6em 0 .6em 14px;border-left:var(--line-1) solid var(--border)}
.claims p{margin:0}
.by{font:400 var(--text-detail) var(--font-mono);color:var(--text-muted);margin-top:.25em;display:flex;flex-wrap:wrap;gap:2px 10px;align-items:center}
.by b{font-weight:500;color:var(--text)}
.ts{font-variant-numeric:tabular-nums;color:var(--accent);text-decoration:none;font-weight:500}
a.ts::before{content:"\\25B8\\00a0"}
a.ts:hover{text-decoration:underline}
.xtabs{display:flex;align-items:center;flex-wrap:wrap;gap:var(--space-1) var(--space-5);margin:0 0 var(--space-6);font:500 var(--text-caption) var(--font-mono);letter-spacing:.09em;text-transform:uppercase}
.xtabs a{padding:var(--space-2) 0 6px;border-bottom:var(--line-2) solid transparent;color:var(--text-muted);text-decoration:none}
.xtabs a:hover{color:var(--accent)}.xtabs a[aria-current]{color:var(--text);border-bottom-color:var(--accent)}
.mark.x{background:var(--text);color:var(--base)}.mark.x svg{width:11px;height:11px}
.lensname,h2.lensname{display:flex;align-items:center;margin:var(--space-8) 0 0;font:500 var(--text-caption) var(--font-mono);letter-spacing:.09em;text-transform:uppercase;color:var(--text-muted)}
.lensname::before,.lensname::after,.day-title::before,.day-title::after{display:none}
.lensname .mark{margin-right:var(--space-2)}
.blurb{list-style:none;margin:var(--space-2) 0 0;padding:0}
.blurb li{padding:var(--space-3) 0;border-top:var(--line-1) solid var(--border);font-size:var(--text-section);line-height:1.55}
.cite{display:inline-block;min-width:24px;margin-left:var(--space-1);padding:0 5px;text-align:center;font:500 var(--text-caption)/1.7 var(--font-mono);color:var(--accent);
border:var(--line-1) solid var(--border);border-radius:var(--radius-xs);text-decoration:none;vertical-align:1px}
.cite:hover{border-color:var(--accent);background:var(--accent-soft)}
.note{margin-top:var(--space-6)}
.theme{margin-top:var(--space-6);scroll-margin-top:var(--space-4)}
.thead{display:flex;align-items:flex-start;gap:var(--space-3)}
.thead h3,.thead h4{flex:1;margin:0 0 var(--space-2);font:600 var(--text-heading)/1.3 var(--font-sans);letter-spacing:-.015em;text-wrap:balance}
.done{flex:none;width:32px;height:32px;border:var(--line-1) solid var(--border);border-radius:50%;background:none;color:var(--text-muted);cursor:pointer;font-size:15px}
.done:hover{border-color:var(--accent);color:var(--accent)}.done[aria-pressed=true]{background:var(--accent);border-color:var(--accent);color:var(--base)}
.theme.read p.blurb,.theme.read .tposts{display:none}.theme.read .thead h3,.theme.read .thead h4{color:var(--text-muted)}
.tposts>summary{cursor:pointer;color:var(--accent);font:500 var(--text-caption) var(--font-mono);padding:var(--space-1) 0;list-style:none}
.tposts>summary::before{content:"▸ "}.tposts[open]>summary::before{content:"▾ "}.tposts>summary::-webkit-details-marker{display:none}
p.blurb{margin:0 0 var(--space-2);font-size:var(--text-section);line-height:1.6;max-width:68ch}
.posts{list-style:none;padding:0;margin:0}
.more .post{grid-template-columns:1fr}
.post{display:grid;grid-template-columns:2.6rem 1fr;padding:var(--space-6) 0;border-top:var(--line-1) solid var(--border);scroll-margin-top:var(--space-4)}
.post:target{box-shadow:inset var(--line-2) 0 0 var(--accent);background:linear-gradient(90deg,var(--accent-soft),transparent 60%)}
.day{padding:var(--space-6) 0 var(--space-3);border-top:var(--line-1) solid var(--border)}
.day .date{margin:0}
h2.day-title{display:block;margin:var(--space-1) 0 0;font:600 var(--text-heading)/1.28 var(--font-sans);letter-spacing:-.02em;text-transform:none;color:var(--text);text-wrap:balance}
h2.day-title a{text-decoration:none}
.day .lensname{margin-top:var(--space-4)}
.archive{list-style:none;padding:0;margin:0}
.archive li{display:grid;grid-template-columns:12rem 1fr;gap:var(--space-4);padding:var(--space-3) 0;border-top:var(--line-1) solid var(--border)}
.archive a{text-decoration:none}.archive .d{font:400 var(--text-detail) var(--font-mono);color:var(--text-muted)}
.archive a:hover{color:var(--accent)}
.chip{font:500 11.5px/1.7 var(--font-mono);letter-spacing:.04em;padding:0 7px;border:var(--line-1) solid var(--border);border-radius:var(--radius-xs);
color:var(--text);text-decoration:none;background:var(--surface-2)}
a.chip:hover{border-color:var(--accent);color:var(--accent)}
.lede{font:400 var(--text-lede)/1.5 var(--font-sans);color:var(--text-muted);margin:0 0 .4em;max-width:60ch}
.theme{padding:30px 0;border-top:var(--line-1) solid var(--border)}
.theme h3{font:600 var(--text-heading)/1.28 var(--font-sans);letter-spacing:-.02em;margin:0;text-wrap:balance}
.stance{font:500 11.5px var(--font-mono);letter-spacing:.14em;text-transform:uppercase;color:var(--accent)}
.read{border-left:var(--line-2) solid var(--accent);padding-left:14px;margin:.8em 0}
.cites{list-style:none;padding:0;margin:.9em 0 0;font:400 var(--text-detail) var(--font-mono)}
.cites li{padding:2px 0}
.cites a{color:var(--text-muted)}
.cites a:hover{color:var(--accent)}
.more{margin-top:1.6em;font:500 var(--text-detail) var(--font-mono);letter-spacing:.04em}
.more a{color:var(--accent);text-decoration:none}
.more a:hover{text-decoration:underline}
.issues{list-style:none;padding:0;margin:0}
.issues li{padding:13px 0;border-top:var(--line-1) solid var(--border);font-size:1.05rem}
.issues li:first-child{border-top:0;padding-top:0}
.issues a{text-decoration:none}
.tickers{display:flex;flex-wrap:wrap;gap:var(--space-2);padding:0;list-style:none}
.tickers .chip{font-size:var(--text-detail);padding:2px 10px}
.tickers .ct{font:400 var(--text-micro) var(--font-mono);color:var(--text-muted);margin-left:5px}
.top-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--space-3) var(--space-5)}
.top-head h2{margin:0}
.top-head h2::after{display:none}
.windows{display:flex;gap:0;border:var(--line-1) solid var(--border);border-radius:var(--radius-md);overflow:hidden}
.windows button{font:500 var(--text-caption) var(--font-mono);letter-spacing:.04em;color:var(--text-muted);background:none;border:0;border-right:var(--line-1) solid var(--border);
min-height:34px;padding:6px 13px;cursor:pointer}
.windows button:last-child{border-right:0}
.windows button:hover{color:var(--accent)}
.windows button[aria-pressed=true]{color:var(--text-on-accent);background:var(--accent)}
.top{list-style:none;padding:0;margin:1.6em 0 0}
.top .entry{padding:24px 0;grid-template-columns:1fr}
.meter{position:relative;display:inline-block;vertical-align:middle;margin-right:10px;width:50px;height:10px;background:repeating-linear-gradient(90deg,var(--border) 0 3px,transparent 3px 5px)}
.meter::after{content:"";position:absolute;inset:0;width:calc(var(--n) * 10%);background:repeating-linear-gradient(90deg,var(--accent) 0 3px,transparent 3px 5px)}
.top-title{display:flex;flex-wrap:wrap;align-items:center;gap:6px 18px}
.fresh{margin:var(--space-3) 0 0;font:500 var(--text-small)/1.4 var(--font-mono)}
.fresh::before{content:"";display:inline-block;width:8px;height:8px;margin-right:8px;border-radius:50%;background:var(--accent)}
.fresh .meta{margin-left:.35em}
.top .entry[data-new]{border-left:3px solid var(--accent);padding-left:14px;background:linear-gradient(90deg,color-mix(in srgb,var(--accent) 7%,transparent),transparent 70%)}
.top .entry.hit{outline:2px solid var(--accent);outline-offset:4px}
.top.js .entry.fold{cursor:pointer}.top.js .entry.fold .epb,.top.js .entry.fold .eps{cursor:auto}.top.js .entry.fold a{cursor:pointer}
.entry.fold h3{position:relative;padding-right:2em}
.epc-t{position:absolute;right:0;top:50%;display:none;width:1.6em;height:1.6em;transform:translateY(-50%);padding:0;border:0;background:none;color:inherit;cursor:pointer}
.top.js .entry.fold .epc-t{display:inline-flex;align-items:center;justify-content:center}
.epc-t::after{content:"";width:.5em;height:.5em;border:solid var(--text-muted);border-width:0 2px 2px 0;transform:rotate(-45deg);transition:transform .15s}
.epc-t[aria-expanded=true]::after{transform:rotate(45deg)}
.epc-t:focus-visible{outline:2px solid var(--accent);outline-offset:4px}
.epb{margin-top:.2em}.epb .claims{margin-top:.6em}.epb .meta{margin-top:.8em}
.eps{margin-top:.6em}.eps:empty{margin:0}
.eps.busy::before{content:"";display:inline-block;width:.9em;height:.9em;margin-right:.5em;vertical-align:-.12em;border:2px solid var(--border);border-top-color:var(--text-muted);border-radius:50%;animation:epspin .8s linear infinite}
@keyframes epspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.eps.busy::before{animation:none}}
.new{font:500 10.5px var(--font-mono);letter-spacing:.1em;text-transform:uppercase;color:var(--accent);border:var(--line-1) solid var(--accent);border-radius:var(--radius-xs);padding:0 5px;margin-right:8px}
.mark{position:relative;display:inline-flex;align-items:center;justify-content:center;box-sizing:border-box;width:28px;height:20px;margin-right:7px;vertical-align:middle;
font:700 var(--text-micro)/1 var(--font-mono);letter-spacing:.03em;color:var(--text-on-accent);background:var(--accent);border-radius:var(--radius-sm);cursor:default}
.mark.signals{background:var(--signals);color:var(--on-signals);font:700 14px/1 var(--font-sans)}
.mark.social{background:#e00;color:#fff}
.mark svg{width:14px;height:14px;display:block}
.claims.influencer li{border-left-style:dashed;border-left-color:var(--border-strong)}
[data-tip]{position:relative}
[data-tip]::before{content:attr(data-tip);display:none;position:absolute;left:0;bottom:calc(100% + 8px);z-index:20;width:max-content;max-width:min(260px,80vw);padding:7px 10px;
font:400 var(--text-caption)/1.45 var(--font-sans);letter-spacing:0;text-transform:none;white-space:normal;text-align:left;color:var(--base);background:var(--text);border-radius:var(--radius-md);pointer-events:none;
animation:tip .12s ease-out}
[data-tip]:hover::before,[data-tip]:focus-visible::before{display:block}
@keyframes tip{from{opacity:0;transform:translateY(3px)}}
.lensbar{display:flex;flex-wrap:wrap;gap:var(--space-2);margin:14px 0 0}
.lensbar button{--c:var(--accent);display:inline-flex;align-items:center;gap:var(--space-2);min-height:34px;font:500 var(--text-caption) var(--font-mono);letter-spacing:.06em;color:var(--text-muted);
background:none;border:var(--line-1) solid var(--border);border-radius:var(--radius-md);padding:4px 12px 4px 6px;cursor:pointer}
.lensbar button:first-child{padding-left:11px}
.lensbar button .mark{margin:0;pointer-events:none}
.lensbar [data-lens=signals]{--c:var(--signals)}
.lensbar button:hover{color:var(--text);border-color:var(--c)}
.lensbar button[aria-pressed=true]{color:var(--text);border-color:var(--c);background:var(--surface-2);box-shadow:inset 0 -2px 0 var(--c)}
.lens-off,.topic-off{display:none!important}
.seg{display:flex;flex-wrap:nowrap;gap:var(--space-1);margin:0 0 var(--space-5)}
.seg a,.seg button{--c:var(--bucket-valuation);display:inline-flex;align-items:center;gap:6px;min-height:28px;font:500 var(--text-micro) var(--font-mono);letter-spacing:.06em;color:var(--text-muted);
background:none;border:var(--line-1) solid var(--border);border-radius:var(--radius-md);padding:2px 9px;text-decoration:none;cursor:pointer}
.seg a{padding-left:5px}
.seg a:hover,.seg button:hover{color:var(--text);border-color:var(--c)}
.seg a[aria-current],.seg button[aria-pressed=true]{color:var(--text);border-color:var(--c);background:var(--surface-2)}
.seg .mark{margin:0;width:22px;height:16px;pointer-events:none}.seg .mark svg{width:11px;height:11px}
.seg.sort{margin:var(--space-3) 0 0}.seg.sort button{--c:var(--accent)}
.embed .open{font:500 12.5px var(--font-mono);color:var(--accent);text-decoration:none}
.embed{max-width:550px;min-height:2.4em;margin-top:.9em}
.facets{display:flex;flex-wrap:wrap;gap:var(--space-2);margin:14px 0 0}
.facets select,.facets input{font:400 var(--text-detail) var(--font-mono);color:var(--text);background:var(--surface-2);border:var(--line-1) solid var(--border);border-radius:var(--radius-md);padding:6px 9px;max-width:100%}
.facets input{flex:1 1 100%;font-size:15px;padding:10px 12px}
.facets select{flex:1 1 150px;min-width:0}
.topics{display:flex;flex-wrap:wrap;gap:6px;margin:14px 0 0;padding:0;list-style:none}
.topics button{font:500 var(--text-caption) var(--font-mono);letter-spacing:.04em;color:var(--text-muted);background:var(--surface-2);border:var(--line-1) solid var(--border);border-radius:var(--radius-xs);padding:2px 9px;cursor:pointer}
.topics button:hover{color:var(--accent);border-color:var(--accent)}
.topics button[aria-pressed=true]{color:var(--text-on-accent);background:var(--accent);border-color:var(--accent)}
.topics .grp{font:500 var(--text-micro) var(--font-mono);letter-spacing:.12em;text-transform:uppercase;color:var(--text-muted);align-self:center;margin:0 2px 0 0}
.cos{display:inline-flex;flex-wrap:wrap;gap:var(--space-1);margin-left:8px;vertical-align:middle}
.why{font:400 11.5px var(--font-mono);color:var(--text-muted)}
.more-btn{font:500 var(--text-detail) var(--font-mono);color:var(--accent);background:none;border:var(--line-1) solid var(--border);border-radius:var(--radius-md);padding:8px 14px;cursor:pointer;margin-top:1.4em}
footer{border-top:var(--line-1) solid var(--border);padding:26px 0 40px;color:var(--text-muted);font:400 var(--text-caption) var(--font-mono);letter-spacing:.03em}
footer a{color:var(--text-muted)}
footer .wrap{display:flex;flex-wrap:wrap;justify-content:space-between;gap:6px var(--space-5)}
footer .upd{flex:1 0 100%;margin:0;font-size:var(--text-micro);letter-spacing:.04em}
@media (max-width:480px){h1{font-size:1.4rem}.wrap{padding:0 16px}header.site .wrap{flex-wrap:wrap;row-gap:var(--space-3);position:relative}.bar{display:contents}.id{width:100%}.theme-switch{position:absolute;top:0;right:16px}nav{order:3;flex:1 1 auto;gap:6px 10px}nav a{font-size:var(--text-micro);letter-spacing:.03em}.menu{order:4;position:static}.menu ul{left:16px;right:16px;top:calc(100% + 8px)}.entry{grid-template-columns:1.9rem 1fr;padding:24px 0}.post{grid-template-columns:1.9rem 1fr}.archive li{grid-template-columns:1fr;gap:0}
.entry h3,.theme h3{font-size:1.2rem}.lede{font-size:1.08rem}main{padding-top:40px}.listen{display:flex;margin:4px 0 0 -7px}}
"""


def esc(v) -> str:
    return html.escape("" if v is None else str(v), quote=True)


def safe_url(u) -> str:
    u = str(u or "").strip()
    return u if re.match(r"^https?://", u, re.I) else ""


def ext_link(u, text: str, cls: str = "") -> str:
    u = safe_url(u)
    if not u:
        return ""
    c = f' class="{cls}"' if cls else ""
    return f'<a{c} href="{esc(u)}" rel="noopener noreferrer">{esc(text)}</a>'


def fmt_ts(sec) -> str:
    if not isinstance(sec, int) or sec < 0:
        return ""
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def slug(sym: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", sym)


def is_private(t: str) -> bool:
    return t.startswith("private:")


def human_date(iso: str, weekday: bool = False) -> str:
    try:
        d = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return str(iso or "")
    out = f"{MONTHS[d.month - 1]} {d.day}, {d.year}"
    return f"{DAYS[d.weekday()]}, {out}" if weekday else out


def issue_title(r: dict) -> str:
    if r["kind"] == "special":
        return r["title"]
    if r["kind"] == "weekly":
        return f"Week of {human_date(r['date'])}"
    return human_date(r["date"], weekday=True)


THEME_BOOT = "try{var t=localStorage.getItem('sigma-theme');if(t==='light'||t==='dark')document.documentElement.dataset.theme=t}catch(e){}"
_ICON = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
MODE_BUTTON = ('<details class="theme-switch"><summary aria-label="Theme" title="Theme">'
               f'<span data-theme-icon="system">{_ICON}<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg></span>'
               f'<span data-theme-icon="light" hidden>{_ICON}<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/></svg></span>'
               f'<span data-theme-icon="dark" hidden>{_ICON}<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg></span></summary>'
               '<div class="theme-switch-popover" role="group" aria-label="Theme">'
               f'<button type="button" data-theme-choice="system" aria-pressed="true" aria-label="System theme">{_ICON}<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M8 20h8M12 16v4"/></svg><span>System</span></button>'
               f'<button type="button" data-theme-choice="light" aria-pressed="false" aria-label="Light theme">{_ICON}<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4"/></svg><span>Light</span></button>'
               f'<button type="button" data-theme-choice="dark" aria-pressed="false" aria-label="Dark theme">{_ICON}<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg><span>Dark</span></button></div></details>'
               "<script>(()=>{const r=document.documentElement,d=document.querySelector('.theme-switch'),bs=d.querySelectorAll('[data-theme-choice]'),icons=d.querySelectorAll('[data-theme-icon]');"
               "const set=m=>{m==='system'?r.removeAttribute('data-theme'):r.dataset.theme=m;bs.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.themeChoice===m)));icons.forEach(i=>i.hidden=i.dataset.themeIcon!==m)};"
               "let m='system';try{m=localStorage.getItem('sigma-theme')}catch(e){}set(m==='light'||m==='dark'?m:'system');"
               "bs.forEach(b=>b.addEventListener('click',()=>{const m=b.dataset.themeChoice;set(m);try{m==='system'?localStorage.removeItem('sigma-theme'):localStorage.setItem('sigma-theme',m)}catch(e){}d.removeAttribute('open')}))})()</script>")


# Display names and routes of the sections. /tickers/ is the ticker board; /tags/ lists every ticker, person and company.
PODCASTS_NAME, X_NAME = "Podcasts", "X"
FEED_NAME = "Podcasts & YouTube"
SOCIAL_NAME, SOCIAL_PATH, VIDEOS_NAME = "Social", "/social/", "YouTube"  # Social has two sides: YouTube creators at /social/ and X at /x/ (its own pages, unchanged)
SENTIMENT_NAME, SENTIMENT_PATH = "Sentiment", "/sentiment/"  # the ticker board
TICKERS_NAME = "Tickers"  # the list of every ticker with a page, a section of the Tags page; each ticker keeps /tickers/<SYM>.html
TAGS_NAME, TAGS_PATH = "Tags", "/tags/"
OLD_BOARD_PATHS = ("/board/", "/tickers/")  # the board's earlier routes: now redirects (noindex) to SENTIMENT_PATH
NAV_PRIMARY = (("/", "Podcasts & video", "podcasts"), ("/x/", X_NAME, "social"), (SENTIMENT_PATH, SENTIMENT_NAME, "sentiment"))

DAILY_RUNS: set[str] = set()  # names of the daily issues, set by build(): a claim never links one as an issue page (see run_redirect)
SITE_YEAR = 0  # the year of the newest data; set by build(). A date in that year is shown without it.


def updated_text(v: str) -> str:
    """'Updated Oct 27, 9:12 PM PT' for a timestamp, 'Updated Oct 27' for a date alone, '' when it is neither. Pacific time, as the issues are dated."""
    v = str(v or "")
    if len(v) > 10:
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            dt = (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(board.pacific_tz())
            yr = "" if dt.year == SITE_YEAR else f", {dt.year}"
            return f"Updated {MONTHS[dt.month - 1]} {dt.day}{yr}, {dt.hour % 12 or 12}:{dt.minute:02d} {'AM' if dt.hour < 12 else 'PM'} PT"
        except ValueError:
            pass
    try:
        d = date.fromisoformat(v[:10])
    except ValueError:
        return ""
    return f"Updated {MONTHS[d.month - 1]} {d.day}{'' if d.year == SITE_YEAR else f', {d.year}'}"


def newest_of(*dates) -> str:
    """The latest of the date strings that exist, or '' when none does."""
    return max((str(d)[:10] for d in dates if d), default="")


# Vercel Web Analytics: page views only (the Hobby plan has no custom events, so a search is not recorded: its results load without a
# navigation). The queue stub and the script Vercel serves at this path; no cookies, no package. In the HTML pages only, never in
# Markdown, llms.txt or JSON. Web Analytics must also be enabled for the project in the Vercel dashboard; the Notice page says so.
ANALYTICS = ('<script>window.va=window.va||function(){(window.vaq=window.vaq||[]).push(arguments)}</script>'
             '<script defer src="/_vercel/insights/script.js"></script>')


def page(title: str, body: str, depth_nav: str = "", desc: str = "", md: str = "", updated: str = "") -> str:
    """`updated` is the newest date or timestamp behind the page (the newest run for the home page and issue pages, the episode's date,
    the newest claim for a ticker or person, the newest item the board counts, an X edition's scan-window end); it prints as one muted
    line at the top of the footer. Never the build clock, so a rebuild with no new data changes nothing."""
    shown = SITE if title == SITE else title
    cur = ' aria-current="page"'
    link = lambda h, n, k: f'<a href="{h}"{cur if k == depth_nav else ""}>{n}</a>'
    links = "".join(link(*r) for r in NAV_PRIMARY)
    when = updated_text(updated)
    upd = f'<p class="upd">{esc(when)}</p>' if when else ""
    d = f'<meta name="description" content="{esc(desc)}">' if desc else ""
    if md:
        d += f'<link rel="alternate" type="text/markdown" href="{esc(md)}">'
    maker = f'<a class="maker" href="{esc(X_PROFILE)}" rel="me noopener noreferrer">{X_LOGO}{esc(MAKER)}</a>' if MAKER and X_PROFILE else ""
    x_link = f'<a href="{esc(X_PROFILE)}" rel="me noopener noreferrer">X profile</a> · ' if X_PROFILE else ""
    return (f'<!doctype html>\n<html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(shown)}</title>{d}<link rel="alternate" type="application/json" href="/runs.json">'
            f'<link rel="preconnect" href="https://fonts.googleapis.com">'
            f'<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
            f'{ICONS}<script>{THEME_BOOT}</script>{ANALYTICS}<link rel="stylesheet" href="{FONTS}"><link rel="stylesheet" href="/style.css"></head><body>'
            f'<header class="site"><div class="wrap"><div class="id"><a class="brand" href="/">{esc(SITE)}</a>{maker}</div><div class="bar"><nav aria-label="Main">{links}</nav>{MODE_BUTTON}</div></div></header>'
            f'<main><div class="wrap">{body}</div></main>'
            f'<footer><div class="wrap">{upd}'
            f'<span>{x_link}<a href="{NOTICE_PATH}">Notice</a> · <a href="/llms.txt">llms.txt</a></span></div></footer></body></html>\n')


# ---------------------------------------------------------------- loading

def read_json(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def read_jsonl(p: Path) -> list[dict]:
    rows = []
    try:
        for line in p.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if isinstance(r, dict):
                    rows.append(r)
    except OSError:
        pass
    return rows


LINK_FIELDS = ("youtube_url", "apple_url", "spotify_url", "spotify_kind")


def link_fields(meta: dict, claims: list[dict] | None = None) -> dict:
    """Listen links of an episode: episodes.json first, a YouTube link carried by its claims as the fallback."""
    out = {k: meta.get(k) for k in LINK_FIELDS if meta.get(k)}
    if not out.get("youtube_url"):
        out["youtube_url"] = next((c["youtube_url"] for c in claims or [] if c.get("youtube_url")), None)
    return {k: v for k, v in out.items() if v}


def load_themes(d: Path) -> dict | None:
    """published/<run>/themes.json (the resolved file themes.py writes), or None when absent or unusable."""
    t = read_json(d / "themes.json")
    items = [x for x in t.get("themes") or [] if isinstance(x, dict) and x.get("title")] if isinstance(t, dict) else []
    return {**t, "themes": items} if items else None


def load_run(d: Path) -> dict | None:
    name = d.name
    ranked = read_json(d / "ranked.json")
    report = read_json(d / "report.json")
    scores = read_json(d / "scores.json")  # a daily run: every episode it scored, not only the picks
    if not isinstance(ranked, dict):
        ranked = None
    if not isinstance(report, dict):
        report = None
    meta = {m.get("episode_id"): m for m in (read_json(d / "episodes.json", []) or []) if isinstance(m, dict)}
    # Influencer episodes (creators who pick stocks) are scored apart, in scores-influencer.json. Everything about them is
    # split off here, so no interview ranking, show, company, person or count below can see one.
    iscores = read_json(d / "scores-influencer.json")
    iep = [e for e in (iscores.get("episodes") if isinstance(iscores, dict) else None) or [] if isinstance(e, dict) and e.get("episode_id")]
    iids = {e["episode_id"] for e in iep} | {k for k, m in meta.items() if m.get("style") == "influencer"}
    imeta = {k: v for k, v in meta.items() if k in iids}
    meta = {k: v for k, v in meta.items() if k not in iids}
    claims = [c for c in read_jsonl(d / "claims.jsonl") if c.get("episode_id") not in iids]
    if not (ranked or report or claims or iep):
        return None
    title = (ranked or {}).get("title")  # a one-off issue: a chosen set of episodes, titled instead of dated
    weekly = bool((ranked or {}).get("episodes"))
    kind = "special" if title else "weekly" if weekly else "daily"
    date_ = ((ranked or {}).get("week_of") if title or weekly else None) or (report or {}).get("date") or (re.match(r"\d{4}-\d{2}-\d{2}", name) or [""])[0]
    by_ep: dict[str, list[dict]] = {}
    for c in claims:
        by_ep.setdefault(c.get("episode_id", ""), []).append(c)
    eps = []
    if ranked:
        for i, e in enumerate(ranked.get("episodes") or [], 1):
            eid = e.get("episode_id", "")
            cl = by_ep.get(eid) or [{"speaker": c.get("speaker"), "timestamp": c.get("timestamp"), "text": c.get("claim"),
                                      "tickers": c.get("ticker") or [], "novelty": c.get("novelty"),
                                      "verifiable": c.get("verifiable"), "link": ""} for c in e.get("claims") or []]
            m = meta.get(eid, {})
            eps.append({"id": eid, "rank": e.get("rank") or i, "score": e.get("score"), "title": e.get("title"),
                        "show": e.get("source") or m.get("source"), "published": e.get("published"),
                        "reason": None, "url": e.get("url"), "claims": cl, **link_fields(m, cl),
                        "transcript_url": (by_ep.get(eid) or [{}])[0].get("transcript_url") or e.get("transcript_url")})
    else:
        titles = {e.get("episode_id"): e for e in (report or {}).get("essential") or []}
        order = [e.get("episode_id") for e in (report or {}).get("episodes") or []] or list(by_ep)
        for i, eid in enumerate(order, 1):
            cl = by_ep.get(eid, [])
            first = cl[0] if cl else {}
            m = meta.get(eid, {})
            rep = next((e for e in (report or {}).get("episodes") or [] if e.get("episode_id") == eid), {})
            eps.append({"id": eid, "rank": i, "score": first.get("score"),
                        "title": first.get("title") or m.get("title") or rep.get("headline"),
                        "show": first.get("show") or m.get("show") or m.get("source") or titles.get(eid, {}).get("show"),
                        "published": first.get("published") or m.get("published"),
                        "reason": rep.get("headline") if first.get("title") else None,
                        "url": first.get("url") or rep.get("url") or m.get("url"), "claims": cl, **link_fields(m, cl),
                        "transcript_url": first.get("transcript_url") or rep.get("transcript_url")})
    scored = [e for e in ((ranked or (scores if isinstance(scores, dict) else None) or {}).get("episodes") or [])
              if isinstance(e, dict) and isinstance(e.get("score"), int) and e.get("scored_in") in (None, name)]
    own = [e for e in iep if e.get("scored_in") in (None, name)]  # a reused score is shown with the run that made it
    influencer = {"name": name, "meta": imeta, "rubric": iscores.get("rubric") or 1 if isinstance(iscores, dict) else 1,
                  "scored": [e for e in own if isinstance(e.get("score"), int)],
                  "claims": [{"episode_id": e["episode_id"], "title": e.get("title"), "show": e.get("source"), "published": e.get("published"),
                              "url": e.get("url"), "run": name, "speaker": c.get("speaker"), "timestamp": c.get("timestamp"),
                              "text": c.get("claim"), "tickers": [t for t in c.get("ticker") or [] if isinstance(t, str) and t],
                              "novelty": c.get("novelty"), "verifiable": c.get("verifiable"), "link": ""}
                             for e in own for c in e.get("claims") or [] if isinstance(c, dict) and c.get("claim")]}
    return {"name": name, "kind": kind, "title": title, "date": date_, "episodes": eps, "claims": claims, "dir": d, "meta": meta,
            "influencer": influencer, "themes": load_themes(d) if ranked else None, "scored": scored,
            "rubric": (ranked or (scores if isinstance(scores, dict) else None) or {}).get("rubric") or 1}


def load_runs(published: Path) -> list[dict]:
    runs = [r for d in sorted(published.iterdir()) if d.is_dir() and (r := load_run(d))] if published.is_dir() else []
    runs.sort(key=lambda r: (r["date"], r["name"]), reverse=True)
    return runs


# ---------------------------------------------------------------- rendering

def ticker_chip(t: str) -> str:
    if is_private(t):
        return f'<span class="chip">{esc(t[8:])}</span>'
    return f'<a class="chip" href="/tickers/{esc(quote(slug(t)))}.html">{esc(t)}</a>'


def claim_li(c: dict, show_ep: bool = False) -> str:
    ts = fmt_ts(c.get("timestamp"))
    link = safe_url(c.get("link")) or safe_url(c.get("url"))
    stamp = ""
    if ts:
        stamp = (f'<a class="ts" href="{esc(link)}" rel="noopener noreferrer" aria-label="Open at {esc(ts)}">{esc(ts)}</a>'
                 if link else f'<span class="ts">{esc(ts)}</span>')
    tk = "".join(ticker_chip(t) for t in c.get("tickers") or [] if isinstance(t, str))
    who = f'<b>{esc(c.get("speaker"))}</b>' if c.get("speaker") else ""
    ep = ""
    if show_ep:
        run = c.get("run")
        when = human_date(c.get("date") or c.get("published") or "")
        ttl = esc(c.get("title")) if c.get("title") else ""
        if ttl and c.get("_ep_path"):
            ttl = f'<a href="{esc(c["_ep_path"])}">{ttl}</a>'
        bits = " · ".join(x for x in [show_name(c), ttl, esc(when) if when else ""] if x)
        issue = f' · <a href="/runs/{esc(quote(str(run)))}/">Issue</a>' if run and run not in DAILY_RUNS else ""  # a daily issue is a day on the home page, not a page
        ep = f'<div class="meta">{bits}{issue}</div>'
    return f'<li><p>{esc(c.get("text"))}</p><div class="by">{who}{stamp}{tk}</div>{ep}</li>'


LISTEN = (  # (field, css class, label, inline icon); shown in this order, only the ones an episode has
    ("youtube_url", "yt", "Watch on YouTube",
     '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M23.5 6.2a3 3 0 0 0-2.1-2.1C19.5 3.6 12 3.6 12 3.6s-7.5 0-9.4.5A3 3 0 0 0 .5 6.2C0 8.1 0 12 0 12s0 3.9.5 5.8a3 3 0 0 0 2.1 2.1c1.9.5 9.4.5 9.4.5s7.5 0 9.4-.5a3 3 0 0 0 2.1-2.1c.5-1.9.5-5.8.5-5.8s0-3.9-.5-5.8zM9.6 15.6V8.4l6.2 3.6-6.2 3.6z"/></svg>'),
    ("apple_url", "ap", "Listen on Apple Podcasts",
     '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="9.6" r="2.5"/><path d="M12 13c1.7 0 2.6 1.1 2.4 2.7l-.5 3.7c-.1.9-.8 1.5-1.9 1.5s-1.8-.6-1.9-1.5l-.5-3.7C9.4 14.1 10.3 13 12 13z"/><path class="ln" d="M7.6 14.3a5.6 5.6 0 1 1 8.8 0"/><path class="ln" d="M5.2 16.4a8.8 8.8 0 1 1 13.6 0"/></svg>'),
    ("spotify_url", "sp", "Listen on Spotify",
     '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="11"/><path class="cut" d="M5.9 9c4.2-1.2 8.6-.8 12.3 1.3"/><path class="cut" d="M6.7 12.4c3.5-.9 7-.5 10 1.2"/><path class="cut" d="M7.6 15.6c2.7-.6 5.2-.3 7.5.9"/></svg>'),
)


def listen_icons(e: dict) -> str:
    """Small icon links to the episode on YouTube, Apple Podcasts and Spotify, in that order; none for a link that is missing.
    A Spotify link that is only the show's page (spotify_kind "show") says so in its name."""
    out = []
    for field, cls, label, svg in LISTEN:
        u = safe_url(e.get(field))
        if not u:
            continue
        if field == "spotify_url" and e.get("spotify_kind") == "show":
            label = "Show on Spotify"
        out.append(f'<a class="lk {cls}" href="{esc(u)}" rel="noopener noreferrer" aria-label="{esc(label)}" title="{esc(label)}">{svg}</a>')
    tx = safe_url(e.get("transcript_url"))  # the publisher's own transcript; Sigma's full transcripts are not published
    if tx:
        out.append(f'<a class="lk tx" href="{esc(tx)}" rel="noopener noreferrer" aria-label="Read the transcript" title="Read the transcript">'
                   '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path class="ln" d="M6 3h8l4 4v14H6z"/>'
                   '<path class="ln" d="M9 11h6M9 14.5h6M9 18h4"/></svg></a>')
    return f'<span class="listen">{"".join(out)}</span>' if out else ""


def show_name(e: dict) -> str:
    """The show's name, linked to its page when it has one."""
    name = esc(e.get("show") or "")
    return f'<a href="{esc(e["_show_path"])}">{name}</a>' if name and e.get("_show_path") else name


def episode_entry(e: dict, i: int, n_claims: int | None = None) -> str:
    claims = e["claims"] if n_claims is None else e["claims"][:n_claims]
    meta = " · ".join(x for x in [show_name(e), esc(human_date(board.publication_day(e["published"]))) if e.get("published") else ""] if x) + listen_icons(e)
    title = e.get("title") or e.get("id") or ""
    t = ext_link(e.get("url"), title) or esc(title)
    take = f'<p class="take">{esc(e["reason"])}</p>' if e.get("reason") and e["reason"] != title else ""
    cl = f'<ul class="claims">{"".join(claim_li(c) for c in claims)}</ul>'
    anchor = f' id="{esc(episode_anchor(e["id"]))}"' if e.get("id") else ""
    return (f'<article class="entry"{anchor}><div class="n">{i + 1}</div>'
            f'<div><h3>{t}</h3><div class="meta">{meta}</div>{take}{cl}</div></article>')


def shown(r: dict) -> list[dict]:
    return [e for e in r["episodes"] if e["claims"]]


def episode_anchor(eid: str) -> str:
    """id of an episode's entry on its issue page, which a theme's cited lines link to."""
    return "ep-" + slug(eid)


STANCES = {"consensus": "Consensus", "split": "Split", "emerging": "Emerging"}


def came_up_text(t: dict) -> str:
    c = t.get("came_up_in") if isinstance(t.get("came_up_in"), dict) else {}
    n, m = c.get("episodes"), c.get("of")
    if isinstance(n, int) and isinstance(m, int):
        return f"Came up in {n} of {m} episodes"
    return ""


def evidence_of(t: dict) -> list[dict]:
    return [x for x in t.get("evidence") or [] if isinstance(x, dict)]


def theme_anchor(i: int) -> str:
    """id of the i-th theme (0-based) on its issue page, which the home page and /themes/ link to."""
    return f"theme-{i + 1}"


def theme_meta(t: dict) -> str:
    stance = f'<span class="stance">{esc(STANCES[t["stance"]])}</span>' if t.get("stance") in STANCES else ""
    return " · ".join(x for x in [stance, esc(came_up_text(t))] if x)


def theme_html(t: dict, on_page: set, i: int = 0, base: str = "") -> str:
    """One theme in full. base is the issue page's path when rendered elsewhere, so cited lines still reach their episode."""
    meta = theme_meta(t)
    chips = "".join(ticker_chip(x) for x in t.get("tickers") or [] if isinstance(x, str) and x)
    lines = []
    for ev in evidence_of(t):
        label = ", ".join(str(x) for x in [ev.get("speaker"), ev.get("show")] if x)
        if not label:
            continue
        tip = f' title="{esc(ev["claim"])}"' if ev.get("claim") else ""
        eid = ev.get("episode_id")
        lines.append(f'<li><a href="{esc(base)}#{esc(episode_anchor(eid))}"{tip}>{esc(label)}</a></li>' if eid in on_page else f"<li>{esc(label)}</li>")
    title = f'<a href="{esc(base)}#{theme_anchor(i)}">{esc(t["title"])}</a>' if base else esc(t["title"])
    return (f'<article class="theme" id="{theme_anchor(i)}"><h3>{title}</h3>'
            + (f'<div class="meta">{meta}</div>' if meta else "")
            + (f'<p class="read">{esc(t["summary"])}</p>' if t.get("summary") else "")
            + (f'<div class="by">{chips}</div>' if chips else "")
            + (f'<ul class="cites">{"".join(lines)}</ul>' if lines else "") + "</article>")


def themes_html(r: dict) -> str:
    th = r.get("themes")
    if not th:
        return ""
    on_page = {e["id"] for e in shown(r)}
    lede = f'<p class="lede">{esc(th["headline"])}</p>' if th.get("headline") else ""
    return lede + "<h2>Themes</h2>" + "".join(theme_html(t, on_page, i) for i, t in enumerate(th["themes"])) + "<h2>Episodes</h2>"


def run_page(r: dict) -> str:
    title = issue_title(r)
    eps = "".join(episode_entry(e, i) for i, e in enumerate(shown(r)))
    return page(f"{title} · {SITE}", f'<h1>{esc(title)}</h1>{themes_html(r)}{eps}',
                "podcasts", f"What executives and investors said: {title}", md=run_md_path(r["name"]), updated=r["date"])


def run_href(r: dict) -> str:
    return f'/runs/{quote(r["name"])}/'


def run_list(runs: list[dict]) -> str:
    """Issues as a list; a week with themes shows its headline under the title."""
    items = []
    for r in runs:
        th = r.get("themes") or {}
        sub = f'<div class="meta">{esc(th["headline"])}</div>' if th.get("headline") else ""
        items.append(f'<li><a href="{esc(run_href(r))}">{esc(issue_title(r))}</a>{sub}</li>')
    return f'<ul class="issues">{"".join(items)}</ul>'


def latest_themes(runs: list[dict]) -> dict | None:
    return next((r for r in runs if r.get("themes")), None)


def themes_brief(r: dict) -> str:
    """A week's themes as linked titles with stance and reach, for the home page."""
    href = run_href(r)
    items = "".join(f'<li><a href="{esc(href)}#{theme_anchor(i)}">{esc(t["title"])}</a>'
                    + (f'<div class="meta">{theme_meta(t)}</div>' if theme_meta(t) else "") + "</li>"
                    for i, t in enumerate(r["themes"]["themes"]))
    lede = f'<p class="lede">{esc(r["themes"]["headline"])}</p>' if r["themes"].get("headline") else ""
    return (f'<h2 style="margin-top:0"><a href="{esc(href)}" style="text-decoration:none">Themes · {esc(issue_title(r))}</a></h2>'
            f'{lede}<ul class="issues">{items}</ul><p class="more"><a href="/themes/">All themes &rarr;</a></p>')


LENS_JS = """<script>(()=>{const K='sigma-lens',bs=[...document.querySelectorAll('.lensbar button')],ok=new Set(bs.map(b=>b.dataset.lens));
function get(){let l=new URLSearchParams(location.search).get('lens');if(l===null)try{l=localStorage.getItem(K)}catch(e){}return ok.has(l)?l:ok.has('')?'':bs[0].dataset.lens}
function paint(l){const r=document.documentElement;l?r.dataset.lens=l:delete r.dataset.lens;bs.forEach(b=>b.setAttribute('aria-pressed',b.dataset.lens===l));
document.querySelectorAll('.lf').forEach(x=>x.classList.toggle('lens-off',!!l&&!(' '+x.dataset.l+' ').includes(' '+l+' ')));
document.querySelectorAll('[data-sec]').forEach(x=>x.classList.toggle('lens-off',!x.querySelector('.lf:not(.lens-off)')));
document.dispatchEvent(new CustomEvent('sigma-lens',{detail:l}))}
window.sigmaLens={get,set(l){try{l?localStorage.setItem(K,l):localStorage.removeItem(K)}catch(e){}
const u=new URL(location);if(u.searchParams.has('lens')){l?u.searchParams.set('lens',l):u.searchParams.delete('lens');history.replaceState(null,'',u)}paint(l)}};
bs.forEach(b=>b.addEventListener('click',()=>sigmaLens.set(b.dataset.lens)));
document.readyState==='loading'?document.addEventListener('DOMContentLoaded',()=>paint(get())):paint(get())})()</script>"""


def lens_bar(ent: ents.Entities, everything: bool = True) -> str:
    """Buttons that narrow a page to one lens; 'All' clears it. The pick is kept in localStorage and in ?lens=.
    `everything=False` (the X pages) drops 'All': trading and working with agents are different reads, so a page shows one,
    Signals first."""
    if not ent.lenses:
        return ""
    btns = ('<button type="button" data-lens="" aria-pressed="true">All</button>' if everything else "") + "".join(
        f'<button type="button" data-lens="{esc(lid)}" aria-pressed="false">'
        f'{lens_mark(ent, lid, False)}{esc(l.get("name") or lid)}</button>' for lid, l in ent.lenses.items())
    return f'<div class="lensbar" role="group" aria-label="Lens">{btns}</div>{LENS_JS}'


SOCIAL_TIP = "YouTube: creators who pick stocks, rated on their calls apart from the interviews"
YT_LOGO = '<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path fill="currentColor" d="M9 7.5v9l7.5-4.5z"/></svg>'


def social_mark(tip: bool = True) -> str:
    """The YouTube tile, like a lens tile: it marks a creator episode and the YouTube side of Social."""
    t = f' data-tip="{SOCIAL_TIP}" aria-label="{SOCIAL_TIP}" role="img" tabindex="0"' if tip else ' aria-hidden="true"'
    return f'<span class="mark social"{t}>{YT_LOGO}</span>'


def social_switch(cur: str, has_x: bool = True) -> str:
    """YouTube | X, the two sides of Social, at the top of every page of both. Plain links; the page you are on is current."""
    on = ' aria-current="page"'
    x = f'<a href="/x/"{on if cur == "x" else ""}>{x_mark()}{X_NAME}</a>' if has_x else ""
    return (f'<nav class="seg" aria-label="{SOCIAL_NAME}">'
            f'<a href="{SOCIAL_PATH}"{on if cur == "videos" else ""}>{social_mark(False)}{VIDEOS_NAME}</a>{x}</nav>')


SORTS = (("rating", "Rating"), ("newest", "Newest"))
# One list can be read two ways. The server writes it in its default order, so a page works without a script; the reader's other pick
# reorders it here. Every row carries data-s (rating) and data-d (date); a tie keeps the row's place in the default order (data-i).
SORT_JS = """<script>(()=>{const g=document.querySelector('.sort'),ol=g&&document.getElementById(g.dataset.list);if(!ol)return;
const K='sigma-sort-'+(g.dataset.key||g.dataset.list),bs=[...g.querySelectorAll('button')],rows=[...ol.children];rows.forEach((r,i)=>r.dataset.i=i);
function paint(s,save){bs.forEach(b=>b.setAttribute('aria-pressed',b.dataset.s===s));
rows.slice().sort((a,b)=>(s==='rating'?b.dataset.s-a.dataset.s:(a.dataset.published||a.dataset.d)<(b.dataset.published||b.dataset.d)?1:(a.dataset.published||a.dataset.d)>(b.dataset.published||b.dataset.d)?-1:0)||a.dataset.i-b.dataset.i).forEach(r=>ol.append(r));
if(save)try{localStorage.setItem(K,s)}catch(e){}}
g._paint=paint;bs.forEach(b=>b.addEventListener('click',()=>paint(b.dataset.s,1)));let s=g.dataset.default;try{const v=localStorage.getItem(K);if(v==='rating'||v==='newest')s=v}catch(e){}
g.hidden=false;paint(s)})()</script>"""


def sort_bar(list_id: str, default: str, key: str = "") -> str:
    """Rating | Newest for the list `list_id`, which is written in the `default` order. Hidden until the script runs, since it does nothing without it.
    Both the home page's list and /social/ open on Newest (owner: the home page is where a reader checks what came out today; Rating is one click away). The reader's
    pick is kept per list in the browser (`sigma-sort-<list id>`)."""
    btns = "".join(f'<button type="button" data-s="{k}" aria-pressed="{"true" if k == default else "false"}">{n}</button>' for k, n in SORTS)
    key_attr = f' data-key="{key}"' if key else ""
    return f'<div class="seg sort" role="group" aria-label="Sort" data-list="{list_id}" data-default="{default}"{key_attr} hidden>{btns}</div>'


WINDOWS = (("7", "Week"), ("30", "Month"), ("90", "3 months"), ("0", "All"))
TOP_JS = """<script>(()=>{const rows=[...document.querySelectorAll('#top>li')],none=document.getElementById('top-none'),bs=[...document.querySelectorAll('.windows button')];
bs.forEach(button=>button.dataset.label=button.textContent);
function cutoff(days){if(!+days)return '';const parts=Object.fromEntries(new Intl.DateTimeFormat('en',{timeZone:'America/Los_Angeles',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date()).map(part=>[part.type,part.value]));
return new Date(Date.parse(parts.year+'-'+parts.month+'-'+parts.day+'T00:00:00Z')-(days-1)*864e5).toISOString().slice(0,10)}
let cur='7';function show(days,save){cur=days;const cut=cutoff(days),lens=window.sigmaLens?sigmaLens.get():'';let count=0;
const matches=row=>!lens||(' '+row.dataset.l+' ').includes(' '+lens+' ');
rows.forEach(row=>{const on=(row.dataset.w||row.dataset.d)>=cut&&matches(row);row.hidden=!on;count+=on});none.hidden=count>0;
bs.forEach(button=>{const start=cutoff(button.dataset.w),total=rows.filter(row=>(row.dataset.w||row.dataset.d)>=start&&matches(row)).length;
button.textContent=button.dataset.label+' ('+total+')';button.setAttribute('aria-pressed',String(button.dataset.w===days))});
if(save)try{localStorage.setItem('sigma-window-2',days)}catch(e){}}
bs.forEach(button=>button.addEventListener('click',()=>show(button.dataset.w,1)));let days='7';try{days=localStorage.getItem('sigma-window-2')||days}catch(e){}
document.addEventListener('sigma-lens',()=>show(cur));show(days);
const hash=location.hash.match(/^#d-(\\d{4}-\\d{2}-\\d{2})$/);if(hash){const target=hash[1];show(target>=cutoff('7')?'7':target>=cutoff('30')?'30':target>=cutoff('90')?'90':'0');
const sort=document.querySelector('.sort');sort&&sort._paint&&sort._paint('newest');
const hit=[...document.querySelectorAll('#top>li')].find(row=>!row.hidden&&row.dataset.d<=target);if(hit){hit.classList.add('hit');hit.scrollIntoView()}}})()</script>"""



# An opened home-page row (li.fold) fills from its own small fragment (claims_path): about 2 KB, 6 KB at most, against 137 KB for every row's
# summaries in the page itself. The newest day's rows (at most EPC_AHEAD) are fetched one at a time when the browser is idle, any other row when a
# pointer, finger or the keyboard reaches it, so opening one is usually instant; if it is not in yet a loading line shows. Without a script the
# title stays a link to the episode's page; the script turns it into a disclosure button (aria-expanded) and the whole card toggles on a click
# that is not on a link or a control. A failed fragment says so, links the page, and is tried again on the next open, not on every hover.
EPC_AHEAD = 8
EPC_JS = """<script>(()=>{const top=document.getElementById('top');const rows=top&&[...top.querySelectorAll('li.fold')];if(!rows||!rows.length)return;const cache={},bad={};
const get=(r,retry)=>{const u=r.querySelector('.epb').dataset.src;if(!u)return Promise.resolve('');if(retry)delete bad[u];return cache[u]||(cache[u]=fetch(u,{credentials:'same-origin'}).then(x=>{if(!x.ok)throw 0;return x.text()}).catch(e=>{delete cache[u];bad[u]=1;throw e}))};
const load=r=>{const b=r.querySelector('.epb'),st=r.querySelector('.eps');if(r.dataset.done||!b.dataset.src)return;st.className='meta eps busy';st.textContent='Loading summaries\u2026';
get(r,1).then(h=>{if(r.dataset.done)return;r.dataset.done='1';st.remove();b.insertAdjacentHTML('beforeend',h)}).catch(()=>{if(b.hidden)return;st.className='meta eps';st.textContent='Could not load the summaries. ';const a=document.createElement('a');a.href=b.dataset.page;a.textContent='Open the episode page';st.append(a,'.')})};
const flip=r=>{const t=r.querySelector('.epc-t'),b=r.querySelector('.epb'),o=t.getAttribute('aria-expanded')!=='true';t.setAttribute('aria-expanded',o);b.hidden=!o;if(o)load(r);else{const st=r.querySelector('.eps');if(st&&!r.dataset.done){st.textContent='';st.className='meta eps'}}};
top.classList.add('js');
top.addEventListener('click',ev=>{const r=ev.target.closest&&ev.target.closest('li.fold');if(!r||!r.querySelector('.epc-t'))return;const t=ev.target;
if(t.closest('.epb,.eps')||t.closest('a,input,select,textarea,[tabindex]')||(String(getSelection())&&!t.closest('.epc-t')))return;flip(r)});
const near=ev=>{const r=ev.target.closest&&ev.target.closest('li.fold'),b=r&&r.querySelector('.epb');if(b&&b.dataset.src&&b.hidden&&!bad[b.dataset.src])get(r).catch(()=>{})};
['pointerover','pointerdown','focusin'].forEach(n=>top.addEventListener(n,near));
const q=rows.filter(r=>r.hasAttribute('data-new')).slice(0,%d);const idle=window.requestIdleCallback||(f=>setTimeout(f,300));
const next=()=>{const r=q.shift();if(r)get(r).catch(()=>{}).then(()=>idle(next,{timeout:3000}))};idle(next,{timeout:3000});
})()</script>""" % EPC_AHEAD


def rating_hint(n) -> str:
    return f"Rated {n} out of 10."


def rating_bar(e: dict, hint: str = "") -> str:
    """The rating as a bar, with the explanation on hover and focus; nothing for an episode that was not scored."""
    if not isinstance(e.get("score"), int):
        return ""
    h = esc(hint or rating_hint(e["score"]))
    return f'<span class="meter" style="--n:{int(e["score"])}" role="img" tabindex="0" aria-label="{h}" data-tip="{h}"></span>'


def top_episodes(reg: dict) -> list[dict]:
    """Every scored episode at or above the bar, best first, then better tier, then newest (as rank-merge orders)."""
    eps = [e for e in reg.values() if isinstance(e.get("score"), int) and e["score"] >= MIN_SCORE]
    return sorted(eps, key=lambda e: (-e["score"], e.get("tier") or 3, "".join(chr(255 - ord(c)) for c in e["date"]), e["id"]))


def claims_path(eid: str) -> str:
    """The small fragment of one episode's timestamped summaries (bare HTML, fetched when a home-page row is opened)."""
    return f"/episodes/{quote(slug(eid))}.claims.html"


def claims_fragment(e: dict) -> str:
    """What an opened home-page row shows: the episode's summaries with their timestamps, then the way to its own page."""
    cls = "claims influencer" if e.get("influencer") else "claims"
    return (f'<ul class="{cls}">{"".join(claim_li(c) for c in e["claims"])}</ul>'
            f'<p class="meta"><a href="{esc(e["page"])}">Open the episode page</a></p>\n')


def top_entry(e: dict, newest_day: str = "", why: str = "", anchor: str = "", expand: bool = False) -> str:
    """One episode row: lens marks, show, date, rating and the one-line take. `why` says how a company page found it;
    `also` is the same guest's other episodes folded under this row. `expand` makes the row open to the episode's timestamped
    summaries, loaded from claims_path on the first open (the home page). Without a script the title is still a link to the episode's page."""
    title = e.get("title") or e["id"]
    t = f'<a href="{esc(e["page"])}">{esc(title)}</a>' if e.get("page") else (ext_link(e.get("url"), title) or esc(title))
    fold = bool(expand)
    meta = " · ".join(x for x in [show_name(e), esc(human_date(board.publication_day(e["published"]))) if e.get("published") else "", esc(why)] if x) + listen_icons(e)
    take = f'<p class="take">{esc(e["reason"])}</p>' if e.get("reason") else ""
    rated = rating_bar(e, influencer_hint(e["score"]) if e.get("influencer") and isinstance(e.get("score"), int) else "")
    picks = f'<ul class="claims influencer">{"".join(claim_li(c) for c in e["claims"][:5])}</ul>' if e.get("influencer") and e["claims"] else ""
    score = e["score"] if isinstance(e.get("score"), int) else ""
    anchor_attr = f' id="{anchor}"' if anchor else ""
    fresh = " data-new" if newest_day and e["date"][:10] == newest_day else ""
    published = esc(publication_sort_value(e))
    li = f'<li class="entry{" fold" if fold else ""}" data-d="{esc(e["date"])}" data-published="{published}" data-l="{esc(" ".join(e.get("lenses") or []))}" data-s="{score}"{fresh}{anchor_attr}>'
    panel_id = f'epb-{quote(str(e["id"]), safe="")}'
    toggle = f'<button type="button" class="epc-t" aria-label="Toggle details for {esc(title)}" aria-controls="{panel_id}" aria-expanded="false"></button>' if fold else ""
    head = f'<h3>{t}{toggle}</h3><div class="meta">{rated}{e.get("_marks", "")}{meta}</div>{"" if fold else take}{"" if fold else picks}'
    if fold:
        if e.get("page") and e.get("claims"):
            details = f'<div class="epb" id="{panel_id}" data-src="{esc(claims_path(e["id"]))}" data-page="{esc(e["page"])}" hidden>{take}<p class="meta eps" role="status"></p></div>'
        else:
            static_details = take or '<p class="meta">No transcript claims are available.</p>'
            details = f'<div class="epb" id="{panel_id}" hidden>{static_details}</div>'
    else:
        details = ""
    body = details
    return f'{li}<div>{head}{body}</div></li>'


SOCIAL_MAX = 100  # newest influencer videos listed on /social/; the list grows every day


def influencer_hint(n) -> str:
    return f"Rated {n} out of 10 as social commentary."


def social_episodes(ireg: dict) -> list[dict]:
    """The newest SOCIAL_MAX rated influencer episodes at the feed floor, newest first."""
    eligible = (e for e in ireg.values() if isinstance(e.get("score"), int) and e["score"] >= MIN_SCORE)
    return sorted(eligible, key=lambda e: (e["date"], e["id"]), reverse=True)[:SOCIAL_MAX]


def run_redirect(r: dict, home_days: set[str]) -> str:
    """Where a daily issue's address sends a reader: its day on the home page (/#d-DATE), or "" when the home page has no row
    that day (nothing that came out that day met the feed rating floor; the picks may be from the day before). The issue then
    keeps its own page, so its address never lands on an anchor that is not there."""
    day = r["date"][:10]
    return f"/#d-{day}" if r["kind"] == "daily" and day in home_days else ""


def publication_sort_value(episode: dict) -> str:
    for value in (episode.get("published"), episode.get("date")):
        if not value:
            continue
        raw = str(value)
        try:
            moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            continue
        if len(raw) <= 10:
            return moment.date().isoformat()
        moment = moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat(timespec="microseconds")
    return ""


def feed_rows(reg: dict, ireg: dict | None = None) -> list[dict]:
    selected = {}
    for episode in [*top_episodes(reg), *social_episodes(ireg or {})]:
        selected.setdefault(str(episode["id"]), episode)
    rows = sorted(selected.values(), key=lambda episode: str(episode["id"]))
    return sorted(rows, key=publication_sort_value, reverse=True)


def top_html(reg: dict, runs: list[dict] | None = None, ent: ents.Entities | None = None, ireg: dict | None = None) -> str:
    rows = feed_rows(reg, ireg)
    if not rows:
        return ""
    tabs = "".join(f'<button type="button" data-w="{w}" aria-pressed="false">{n}</button>' for w, n in WINDOWS)
    newest_day = max((e["date"][:10] for e in rows), default="")
    seen = set()
    items = []
    for episode in rows:
        day = episode["date"][:10]
        anchor = f"d-{day}" if day and day not in seen else ""
        if day:
            seen.add(day)
        items.append(top_entry(episode, newest_day, anchor=anchor, expand=True))
    return (f'<div class="top-head"><div class="top-title"><h2>{FEED_NAME}</h2></div><div class="windows" role="group" aria-label="Time window">{tabs}</div></div>'
            f'{sort_bar("top", "newest", key="podcasts-youtube-v1")}<ol class="top" id="top">{"".join(items)}</ol>'
            f'<p class="meta" id="top-none" hidden>No items in this window.</p>{SORT_JS}{TOP_JS}{EPC_JS}')


def latest_issue(runs: list[dict]) -> dict:
    """The newest daily, or the newest issue when there is no daily."""
    dated = [r for r in runs if r["kind"] == "daily"] or runs
    return max(dated, key=lambda r: (r["date"], r["name"]))


def index_page(runs: list[dict], reg: dict | None = None, ent: ents.Entities | None = None, md: str = "/index.md", side: str = "", ireg: dict | None = None) -> str:
    """`side` is the Signals panel: with it the page is two columns on a wide screen (podcasts, then the panel), stacked on a phone."""
    if not runs:
        body = top_html(reg or {}, runs, ent, ireg)
        return page(SITE, body or "<h1>Podcasts &amp; YouTube</h1>", "podcasts", SUMMARY, md=md)
    body = top_html(reg or {}, runs, ent, ireg)
    rest = ""
    if tr := latest_themes(runs):
        rest += f'<div style="margin-top:{"3.2em" if body else "0"}">{themes_brief(tr)}</div>'
    anchor = " id=issues"
    for kind, heading in (("weekly", "Weekly issues"), ("special", "Special issues")):  # a daily issue is its day in the Newest list above
        if same := [x for x in runs if x["kind"] == kind]:
            rest += f'<h2{anchor}>{heading}</h2>{run_list(same)}'
            anchor = ""
    main = body + rest
    if side:
        main = f'<div class="duo"><div class="duo-side">{side}</div><div class="duo-main">{main}</div></div>'
    return page(SITE, main, "podcasts", SUMMARY, md=md,
                updated=latest_issue(runs)["date"])  # the newest daily, or the newest issue when there is no daily; a run holds a date, not a time


def social_page(ireg: dict, has_x: bool = True) -> str:
    """The YouTube side of Social: the newest influencer episodes, newest first by default, with the YouTube | X switch on top."""
    rows = "".join(top_entry(e) for e in social_episodes(ireg))
    body = (f'{social_switch("videos", has_x)}<h1>{SOCIAL_NAME}</h1><p class="lede">Videos from creators who pick stocks, rated {MIN_SCORE} or higher on '
            f'their calls and the evidence behind them, apart from the interview ranking.</p>')
    body += f'{sort_bar("social", "newest")}<ol class="top" id="social">{rows}</ol>{SORT_JS}' if rows else f"<p>No videos rated {MIN_SCORE} or higher yet.</p>"
    return page(f"{SOCIAL_NAME} · {SITE}", body, "social", "Videos from creators who pick stocks, rated apart from the interview ranking.", md="/social.md",
                updated=newest_of(*(e["date"] for e in ireg.values())))


def themes_page(runs: list[dict]) -> str:
    """Every week's themes, newest week first, each linking back to its issue."""
    body = "<h1>Themes</h1>"
    for r in runs:
        th = r.get("themes")
        if not th:
            continue
        href = run_href(r)
        on_page = {e["id"] for e in shown(r)}
        body += (f'<h2><a href="{esc(href)}" style="text-decoration:none">{esc(issue_title(r))}</a></h2>'
                 + (f'<p class="lede">{esc(th["headline"])}</p>' if th.get("headline") else "")
                 + "".join(theme_html(t, on_page, i, href) for i, t in enumerate(th["themes"])))
    if not latest_themes(runs):
        body += "<p>No themes yet.</p>"
    return page(f"Themes · {SITE}", body, "themes", "The themes that crossed episodes, week by week.", md="/themes.md",
                updated=newest_of(*(r["date"] for r in runs if r.get("themes"))))


# ---------------------------------------------------------------- ticker board (the Tickers page)

BOARD_CSS = """
.board-head{display:flex;flex-wrap:wrap;align-items:center;justify-content:space-between;gap:var(--space-3);margin:var(--space-6) 0 var(--space-3)}
.board-head h2{margin:0;flex:1}
.board-cols,.board summary{display:grid;grid-template-columns:4.4rem minmax(0,1fr) 10rem 5rem 4rem;gap:var(--space-3);align-items:center;padding:var(--space-3) 0 var(--space-3) 18px}
.board-cols{font:500 var(--text-caption) var(--font-mono);color:var(--text-muted)}
.board{list-style:none;margin:0;padding:0}
.board>li{border-top:var(--line-1) solid var(--border)}
.board summary{position:relative;cursor:pointer;list-style:none}
.board summary::-webkit-details-marker{display:none}
.board summary::before{content:"";position:absolute;left:2px;top:1.3em;width:6px;height:6px;border:solid var(--text-muted);border-width:0 var(--line-1) var(--line-1) 0;transform:rotate(-45deg)}
.board details[open]>summary::before{transform:rotate(45deg)}
.board summary:hover .bt{color:var(--accent)}
.board summary:focus-visible{outline:var(--line-2) solid var(--accent);outline-offset:-2px}
.bt{font:600 var(--text-row) var(--font-mono)}.bt a{text-decoration:none}
.bn{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font:400 var(--text-detail) var(--font-sans);color:var(--text-muted)}
.bs,.st{font:500 var(--text-detail) var(--font-mono)}
.bs.pos,.st.pos{color:var(--positive)}.bs.neg,.st.neg{color:var(--negative)}.bs.mix{color:var(--warning)}.bs.neu,.st.zero{color:var(--text-muted)}
.bmeta{display:contents}.bm,.bl{font:400 var(--text-detail) var(--font-mono);color:var(--text-muted)}
.sent-votes{margin:0 0 var(--space-3) 18px;color:var(--text-muted);font:400 var(--text-detail) var(--font-mono)}
.bi{list-style:none;margin:0;padding:0 0 var(--space-3) 18px}
.bi li{padding:var(--space-2) 0 var(--space-2) var(--space-3);border-left:var(--line-1) solid var(--border)}
.bi p{margin:2px 0 0;font-size:var(--text-row)}
@media(max-width:600px){.board-cols{display:none}.board summary{grid-template-columns:4.8rem minmax(0,1fr);grid-template-areas:"t s" "n n" "m m";gap:2px var(--space-3)}.board .bt{grid-area:t}.board .bn{grid-area:n}.board .bs{grid-area:s}.board .bmeta{display:flex;grid-area:m;gap:var(--space-4)}.board .bi{padding-left:0}}
"""

BOARD_JS = """<script>(()=>{const list=document.getElementById('board'),buttons=[...document.querySelectorAll('[data-o]')];if(!list)return;
const rows=[...list.children];buttons.forEach(button=>button.addEventListener('click',()=>{const order=button.dataset.o;
rows.slice().sort((a,b)=>(order==='bull'?+b.dataset.net-a.dataset.net:order==='bear'?+a.dataset.net-b.dataset.net:+b.dataset.voices-a.dataset.voices)).forEach(row=>list.append(row));
buttons.forEach(other=>other.setAttribute('aria-pressed',String(other===button)))}))})()</script>"""


def short_date(iso: str) -> str:
    """A short month and day."""
    return human_date(iso).rsplit(",", 1)[0]


def board_row(r: dict, page_sym: str = "") -> str:
    label = r["label"]
    cls = signals_sentiment.CLASS[r["label"]]
    name = r.get("market_label") or r["ticker"]
    title = f'<a href="{esc(ticker_path(page_sym))}">{esc(name)}</a>' if page_sym else esc(name)
    items = "".join(
        f'<li><b>{esc(item["speaker"])}</b> · <span class="st {"pos" if item["vote"] > 0 else "neg" if item["vote"] < 0 else "zero"}">{esc(signals_sentiment.label_for(item["vote"]))}</span>'
        + "".join(f'<p>{esc(short_date(source["date"]))}'
                  + (f' · {esc(source["where"])}' if source["where"] and source["where"] != item["speaker"] else "")
                  + (f' · {ext_link(source["link"], "Source", "ts")}' if safe_url(source["link"]) else "")
                  + f' · {esc(signals_sentiment.label_for(source["stance"]))}: {esc(source["reason"])}</p>'
                  for source in item["evidence"]) + '</li>' for item in r["items"])
    votes = f'{r["bull"]} bullish · {r["bear"]} bearish' + (f' · {r["neutral"]} neutral' if r["neutral"] else "")
    return (f'<li data-net="{r["net"]}" data-voices="{r["sources"]}"><details><summary><span class="bt">{title}</span>'
            f'<span class="bn">{esc(r["name"])}</span><span class="bs {cls}">{esc(label)}</span>'
            f'<span class="bmeta"><span class="bm">{r["sources"]} {"voice" if r["sources"] == 1 else "voices"}</span><span class="bl">{esc(short_date(r["last"]))}</span></span>'
            f'</summary><p class="sent-votes">{votes}</p><ul class="bi">{items}</ul></details></li>')






def board_html(sc: dict, pub: dict | None = None) -> str:
    market = sc.get("market") or []
    market_html = ('<h2>Market</h2><ol class="board">' + "".join(board_row(row) for row in market) + '</ol>') if market else ""
    columns = '<div class="board-cols" aria-hidden="true"><span>Ticker</span><span>Company</span><span>Sentiment</span><span>Voices</span><span>Last</span></div>'
    controls = ('<div class="seg" role="group" aria-label="Sentiment order"><button type="button" data-o="voices" aria-pressed="true">Most voices</button>'
                '<button type="button" data-o="bull" aria-pressed="false">Bullish</button><button type="button" data-o="bear" aria-pressed="false">Bearish</button></div>')
    rows = sc["rows"]
    body = (f'<h1>{SENTIMENT_NAME}</h1><p class="meta">Past {sc["days"]} days · {esc(human_date(sc["as_of"]))}</p>{market_html}'
            f'<div class="board-head"><h2>Tickers</h2>{controls}</div>'
            + (columns + '<ol class="board" id="board">' + "".join(board_row(row, page_sym=(pub or {}).get(row["ticker"], "")) for row in rows) + '</ol>' + BOARD_JS
               if rows else '<p>No directional views in this window.</p>'))
    return page(f"{SENTIMENT_NAME} · {SITE}", body, "sentiment", md=md_of(SENTIMENT_PATH),
                updated=newest_of(*(row["last"] for row in rows + market)) or sc["as_of"])


def board_md(sc: dict) -> str:
    out = [f"# {SENTIMENT_NAME}", "", f"Past {sc['days']} days, as of {human_date(sc['as_of'])}.", ""]
    for row in [*(sc.get("market") or []), *sc["rows"]]:
        out += [f"## {row.get('market_label') or row['ticker']}: {row['label']}", "",
                f"{row['bull']} bullish, {row['bear']} bearish, {row['neutral']} neutral; {plural(row['sources'], 'voice')}.", ""]
        for item in row["items"]:
            out += [f"- {mt(item['speaker'])}: {signals_sentiment.label_for(item['vote'])}"]
            out += [f"  - {mlink(source['date'], source['link']) if safe_url(source['link']) else source['date']}: {signals_sentiment.label_for(source['stance'])} · {mt(source['reason'])}"
                    for source in item["evidence"]]
        out += [""]
    return doc(out)


def board_pages(published: Path, reg: dict, ireg: dict, pages: dict) -> tuple[str, str]:
    episodes = {**{key: ("deep", episode["score"]) for key, episode in reg.items()},
                **{key: ("social", episode["score"]) for key, episode in ireg.items()}}
    scores = board.build(published, episodes)
    return board_html(scores, pages), board_md(scores)


# ---------------------------------------------------------------- paths and URLs

def absu(path: str) -> str:
    return BASE_URL.rstrip("/") + path


def run_path(name: str) -> str:
    return f"/runs/{quote(name)}/"


def run_md_path(name: str) -> str:
    return f"/runs/{quote(name)}.md"


def ticker_path(sym: str, ext: str = "html") -> str:
    return f"/tickers/{quote(slug(sym))}.{ext}"


def person_path(pslug: str, ext: str = "html") -> str:
    return f"/people/{quote(pslug)}.{ext}"


def company_path(cid: str, ext: str = "html") -> str:
    return f"/companies/{quote(cid)}.{ext}"


def show_path(name: str, ext: str = "html") -> str:
    return f"/shows/{quote(person_slug(name))}.{ext}"


def creator_path(cid: str, ext: str = "html") -> str:
    return f"/creators/{quote(cid)}.{ext}"


def episode_path(eid: str, ext: str = "html") -> str:
    return f"/episodes/{quote(slug(eid))}.{ext}"


def md_of(path: str) -> str:
    """Markdown twin of an HTML page path."""
    if path == "/":
        return "/index.md"
    if path.endswith("/"):
        return path[:-1] + ".md"
    return re.sub(r"\.html$", ".md", path)


def file_of(path: str) -> str:
    p = unquote(path.lstrip("/"))
    return p + "index.html" if (not p or p.endswith("/")) else p


# ---------------------------------------------------------------- people

GENERIC = {"host", "guest", "unknown", "anchor", "analyst", "panelist", "speaker", "narrator", "moderator", "interviewer",
           "reporter", "journalist", "partner", "unclear", "co-host", "cohost", "unnamed", "other"}
ROLE_TOKENS = {"ceo", "cto", "cfo", "coo", "cio", "cso", "president", "chairman", "founder", "partner", "analyst",
               "economist", "director", "vp", "professor", "engineer", "journalist", "investor"}
ROLE_BASES = {"host", "guest", "co-host", "cohost", "panelist", "speaker", "moderator", "interviewer", "guest host"}
PARTICLES = {"van", "von", "de", "der", "da", "di", "del", "la", "le", "bin", "al", "el", "ter", "den", "du"}
_NAME_WORD = re.compile(r"^(?:[A-Z][A-Za-z'’-]*[a-z]|[A-Z]\.|[A-Z][a-z]+\.)$")


def looks_like_name(s: str) -> bool:
    words = s.split()
    if not 2 <= len(words) <= 5 or not _NAME_WORD.match(words[0]):
        return False
    for w in words:
        if w.lower() in GENERIC or not (_NAME_WORD.match(w) or w in PARTICLES or w in ("II", "III", "Jr.", "Sr.")):
            return False
    return True


def parse_speaker(speaker) -> tuple:
    """'Andy Jassy (Amazon CEO)' -> ('Andy Jassy', 'Amazon CEO'); generic or unclear speakers -> (None, role-or-None)."""
    s = " ".join(str(speaker or "").split())
    if not s:
        return None, None
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", s)
    base, inner = (m.group(1).strip(), m.group(2).strip()) if m else (s, "")
    if looks_like_name(base):
        return base, inner or None
    if not inner or " or " in inner or "unclear" in inner.lower():
        return None, s
    part = inner.split(",")[0].strip()
    if base.lower() in ROLE_BASES and looks_like_name(part):  # "analyst (New Street Research)" is a firm, not a person
        rest = ", ".join(x.strip() for x in inner.split(",")[1:] if x.strip())
        return part, ", ".join(x for x in [base, rest] if x) or None
    toks = inner.split()
    k = len(toks)
    while k > 0 and (_NAME_WORD.match(toks[k - 1]) or toks[k - 1] in PARTICLES) and toks[k - 1].lower() not in GENERIC:
        k -= 1
    if len(toks) - k >= 2 and k > 0 and toks[k - 1].lower().strip(",") in ROLE_TOKENS:
        name = " ".join(toks[k:])
        if looks_like_name(name):
            return name, ", ".join(x for x in [base, " ".join(toks[:k])] if x)
    return None, s


def person_slug(name: str) -> str:
    a = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", a).strip("-")


# ---------------------------------------------------------------- enrichment and collections

def claim_date(c: dict) -> str:
    return str(c.get("date") or c.get("published") or "")[:10]


def claim_ts(c: dict) -> int:
    t = c.get("timestamp")
    return t if isinstance(t, int) else 10 ** 9


def uniq_claims(claims: list[dict]) -> list[dict]:
    """Drop repeats of the same moment (a daily pick and the weekly ranking can both carry it); keeps the first seen."""
    seen, out = set(), []
    for c in claims:
        k = (c.get("episode_id"), c.get("timestamp"), c.get("text"))
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


def ts_link(url: str, ts) -> str:
    """Deep link to a moment: a YouTube watch URL gets &t=<s>s; anything else stays as it is."""
    return f"{url}&t={ts}s" if isinstance(ts, int) and "youtube.com/watch" in url else url


def public_tickers(c: dict) -> list[str]:
    seen = []
    for t in c.get("tickers") or []:
        if isinstance(t, str) and t and not is_private(t) and t not in seen:
            seen.append(t)
    return seen


def enrich(runs: list[dict]) -> dict:
    """Add stable id, person, role and absolute page URLs to every claim (in place). Returns slug -> person info."""
    people: dict[str, dict] = {}
    for r in runs:
        count: dict[str, int] = {}
        for c in r["claims"]:
            eid = c.get("episode_id") or ""
            count[eid] = count.get(eid, 0) + 1
            c.setdefault("run", r["name"])
            c["id"] = f"{r['name']}:{eid}:{count[eid]}"
            name, role = parse_speaker(c.get("speaker"))
            ps = person_slug(name) if name else ""
            c["person"] = name if ps else None
            c["role"] = role
            c["episode_page"] = absu(episode_path(eid)) if eid else None
            c["person_page"] = absu(person_path(ps)) if ps else None
            c["ticker_pages"] = {t: absu(ticker_path(t)) for t in public_tickers(c)}
            m = r["meta"].get(eid) or {}
            if m.get("youtube_url") and not c.get("youtube_url"):  # a video found after the claim was written
                c["youtube_url"] = m["youtube_url"]
                c["link"] = ts_link(m["youtube_url"], c.get("timestamp"))
            for k in ("apple_url", "spotify_url", "spotify_kind"):
                if m.get(k) and not c.get(k):
                    c[k] = m[k]
            c["_ep_path"] = episode_path(eid) if eid else ""
            c["_person_slug"] = ps
    for r in runs:
        for c in uniq_claims(r["claims"]):
            if c["_person_slug"]:
                p = people.setdefault(c["_person_slug"], {"slug": c["_person_slug"], "names": Counter(), "roles": Counter(),
                                                          "claims": []})
                p["names"][c["person"]] += 1
                if c.get("role"):
                    p["roles"][c["role"]] += 1
                p["claims"].append(c)
    for p in people.values():
        p["claims"] = uniq_claims(p["claims"])
        p["name"] = p["names"].most_common(1)[0][0]
    return people


def build_episodes(runs: list[dict]) -> dict:
    """episode_id -> info merged across issues (newest issue wins), including episodes with no claims."""
    reg: dict[str, dict] = {}

    def entry(eid):
        return reg.setdefault(eid, {"id": eid, "title": None, "show": None, "published": None, "url": None,
                                    "youtube_url": None, "apple_url": None, "spotify_url": None, "spotify_kind": None,
                                    "transcript_url": None, "runs": [], "claims": [],
                                    "score": None, "reason": None, "tier": None, "rubric": 0})

    def fill(e, **kw):
        for k, v in kw.items():
            if v and not e.get(k):
                e[k] = v

    for r in runs:
        for c in r["claims"]:
            eid = c.get("episode_id")
            if not eid:
                continue
            e = entry(eid)
            claim_published = c.get("published") or c.get("date")
            manifest_published = (r["meta"].get(eid) or {}).get("published")
            if manifest_published and len(str(manifest_published)) > 10 and str(manifest_published)[:10] == str(claim_published or "")[:10]:
                claim_published = manifest_published
            fill(e, title=c.get("title"), show=c.get("show"), published=claim_published, url=safe_url(c.get("url")),
                 youtube_url=safe_url(c.get("youtube_url")), transcript_url=safe_url(c.get("transcript_url")))
            if r["name"] not in e["runs"]:
                e["runs"].append(r["name"])
            e["claims"].append(c)
        for eid, m in r["meta"].items():
            if eid:
                fill(entry(eid), title=m.get("title"), show=m.get("show") or m.get("source"), published=m.get("published"),
                     url=safe_url(m.get("url")), youtube_url=safe_url(m.get("youtube_url")), apple_url=safe_url(m.get("apple_url")),
                     spotify_url=safe_url(m.get("spotify_url")), spotify_kind=m.get("spotify_kind"))
    for r in reversed(runs):  # oldest issue first: an episode's score is the first one under the newest rubric
        for x in r["scored"]:
            e = entry(x["episode_id"])
            fill(e, title=x.get("title"), show=x.get("source"), published=x.get("published"), url=safe_url(x.get("url")),
                 tier=x.get("tier"))
            if r["rubric"] > e["rubric"]:
                e["score"], e["reason"], e["rubric"] = x["score"], x.get("reason"), r["rubric"]
    for e in reg.values():
        e["claims"] = sorted(claimdedupe.dedupe(uniq_claims(e["claims"]))[0], key=claim_ts)  # two runs can word one moment differently
        e["page"] = episode_path(e["id"]) if e["claims"] else ""
        e["date"] = board.publication_day(e["published"] or max([claim_date(c) for c in e["claims"]] or [""]))
    return reg


def annotate(reg: dict, ent: ents.Entities) -> dict:
    """Add to each episode its show's topics, the companies it is about, the people who spoke, and its lenses.
    An episode is about a company when two claims name it, its title does, or a named speaker is affiliated with it.
    Returns company id -> {name, kind, ticker} for every company found, curated or not."""
    info: dict[str, dict] = {}
    for e in reg.values():
        cl = e["claims"]
        topics = ent.show_topics.get(person_slug(e["show"] or ""), [])
        count: Counter = Counter()
        by_co: dict[str, list[dict]] = {}
        guests: set[str] = set()
        people: dict[str, dict] = {}
        for c in cl:
            for t in {x for x in c.get("tickers") or [] if isinstance(x, str) and x}:
                cid, name, curated = ents.resolve_ticker(ent, t)
                count[cid] += 1
                by_co.setdefault(cid, []).append(c)
                if cid not in info:
                    cur = ent.companies.get(cid) or {}
                    info[cid] = {"name": name, "kind": cur.get("kind") or ("private" if is_private(t) else "public"),
                                 "ticker": cur.get("ticker") or (None if is_private(t) else t), "topics": cur.get("topics") or [],
                                 "curated": curated}
            if c.get("person"):
                ps = c["_person_slug"]
                p = people.setdefault(ps, {"name": c["person"], "slug": ps, "company": "", "role": ""})
                aff = ents.affiliation(ent, ps)
                if aff:
                    p["company"], p["role"] = aff
                    count[aff[0]] += 1
                    guests.add(aff[0])
                elif c.get("role") and not p["role"]:
                    p["role"] = c["role"]
        hits = set(ents.title_hits(ent, e.get("title") or ""))
        for cid in guests | hits:
            if cid not in info:
                cur = ent.companies[cid]
                info[cid] = {"name": cur.get("name") or cid, "kind": cur.get("kind") or "private", "ticker": cur.get("ticker"),
                             "topics": cur.get("topics") or [], "curated": True}
        edges = {cid for cid, n in count.items() if n >= 2} | hits | guests
        e["topics"] = topics
        e["edges"] = {cid: {"claims": count[cid], "guest": cid in guests, "title": cid in hits} for cid in sorted(edges)}
        e["_co_claims"] = {cid: by_co.get(cid, []) for cid in edges}
        e["people"] = list(people.values())
        public = sum(1 for c in cl if public_tickers(c))
        roles = [x for x in [e.get("title")] + [c.get("role") for c in cl] + [q["role"] for q in people.values()] if x]
        e["lenses"] = ents.lenses_of(ent, topics, list(edges), public, roles)
        e["_marks"] = "".join(lens_mark(ent, lid) for lid in e["lenses"])
    return info


def lens_tip(l: dict) -> str:
    return f'{l.get("name")}: {l.get("about")}'


def lens_mark(ent: ents.Entities, lid: str, tip: bool = True) -> str:
    """The small tile that says which lens an episode is in; hovering or focusing it says what the lens means."""
    l = ent.lenses.get(lid) or {}
    t = f' data-tip="{esc(lens_tip(l))}" aria-label="{esc(lens_tip(l))}" role="img" tabindex="0"' if tip else ' aria-hidden="true"'
    return f'<span class="mark {esc(lid)}"{t}>{esc(l.get("mark") or lid)}</span>'


def build_companies(reg: dict, info: dict) -> dict:
    """company id -> {id, name, kind, ticker, topics, episodes: [(episode, edge)], claims, people, lenses}."""
    cos: dict[str, dict] = {}
    for e in sorted(reg.values(), key=lambda e: (e["date"], e["id"]), reverse=True):
        for cid, ed in e.get("edges", {}).items():
            c = cos.setdefault(cid, {"id": cid, **info[cid], "episodes": [], "claims": [], "people": {}, "lenses": set()})
            c["episodes"].append((e, ed))
            c["claims"] += e["_co_claims"].get(cid, [])
            c["lenses"] |= set(e["lenses"])
            for p in e["people"]:
                if p["company"] == cid:
                    c["people"][p["slug"]] = p
    for c in cos.values():
        c["claims"] = newest_first(uniq_claims(c["claims"]))
        c["lenses"] = sorted(c["lenses"])
    return cos


def collect_tickers(runs: list[dict]) -> tuple[dict, dict]:
    pub: dict[str, list[dict]] = {}
    priv: dict[str, list[dict]] = {}
    for r in runs:
        for c in r["claims"]:
            for t in set(x for x in c.get("tickers") or [] if isinstance(x, str) and x):
                (priv if is_private(t) else pub).setdefault(t[8:] if is_private(t) else t, []).append(c)
    return {k: uniq_claims(v) for k, v in pub.items()}, {k: uniq_claims(v) for k, v in priv.items()}


def newest_first(claims: list[dict]) -> list[dict]:
    claims = sorted(claims, key=claim_ts)
    return sorted(claims, key=lambda c: (claim_date(c), c.get("episode_id") or ""), reverse=True)


# ---------------------------------------------------------------- HTML pages: tickers, people, episodes

def tickers_chips(pub: dict) -> str:
    chips = "".join(
        f'<li><a class="chip" href="{esc(ticker_path(t))}">{esc(t)}</a><span class="ct">{len(v)}</span></li>'
        for t, v in sorted(pub.items(), key=lambda kv: (-len(kv[1]), kv[0])))
    return f'<ul class="tickers">{chips}</ul>'


def ticker_page(sym: str, claims: list[dict], social: list[dict] = ()) -> str:
    """Interview claims first; claims from influencer episodes follow under their own heading, in a dashed rule."""
    claims = sorted(claims, key=lambda c: (claim_date(c), c.get("score") or 0), reverse=True)
    li = "".join(claim_li(c, show_ep=True) for c in claims)
    body = f'<h1>{esc(sym)}</h1>' + (f'<ul class="claims">{li}</ul>' if claims else "")
    if social:
        body += f'<h2>Social</h2><ul class="claims influencer">{"".join(claim_li(c, show_ep=True) for c in newest_first(list(social)))}</ul>'
    return page(f"{sym} · {SITE}", body, "tags", md=md_of(ticker_path(sym)), updated=newest_of(*(claim_date(c) for c in [*claims, *social])))


def people_chips(people: dict) -> str:
    chips = "".join(
        f'<li><a class="chip" href="{esc(person_path(p["slug"]))}">{esc(p["name"])}</a><span class="ct">{len(p["claims"])}</span></li>'
        for p in sorted(people.values(), key=lambda p: (-len(p["claims"]), p["name"])))
    return f'<ul class="tickers">{chips}</ul>'


def roles_of(p: dict) -> list[str]:
    return [r for r, _ in p["roles"].most_common()]


def person_page(p: dict, aff: tuple | None = None, cos: dict | None = None) -> str:
    roles = roles_of(p)
    co = (cos or {}).get(aff[0]) if aff else None
    where = (f'<a href="{esc(company_path(co["id"]))}">{esc(co["name"])}</a>' + (f' · {esc(aff[1])}' if aff[1] else "")) if co else ""
    sub = f'<p class="meta">{where}</p>' if where else ""
    sub += f'<p class="meta">{esc(" · ".join(roles))}</p>' if roles else ""
    li = "".join(claim_li(c, show_ep=True) for c in newest_first(p["claims"]))
    return page(f"{p['name']} · {SITE}", f'<h1>{esc(p["name"])}</h1>{sub}<ul class="claims" style="margin-top:2em">{li}</ul>',
                "tags", md=md_of(person_path(p["slug"])), updated=newest_of(*(claim_date(c) for c in p["claims"])))


def collect_shows(reg: dict) -> dict[str, list[dict]]:
    """show name -> its episodes with claims, newest first."""
    by: dict[str, list[dict]] = {}
    for e in sorted(reg.values(), key=lambda e: (e["date"], e["id"]), reverse=True):
        if e["claims"] and e["show"]:
            by.setdefault(e["show"], []).append(e)
    return by


def by_claims(shows: dict) -> list[tuple]:
    return sorted(shows.items(), key=lambda kv: (-sum(len(e["claims"]) for e in kv[1]), kv[0]))


def show_topics(ent: ents.Entities, name: str) -> list[str]:
    return ent.show_topics.get(person_slug(name or ""), [])


def tag_groups(shows: dict, ent: ents.Entities) -> list[tuple]:
    """[(topic, label, [(show, episodes), ...]), ...] in the order of entities.json (group by group); untagged shows last, under Other."""
    ranked = by_claims(shows)
    order = [t for g in ent.groups for t in g["topics"]]
    order += [t for t in ent.topic_names if t not in order]
    groups = [(t, ent.topic_names[t], [kv for kv in ranked if t in show_topics(ent, kv[0])]) for t in order]
    groups.append(("other", "Other", [kv for kv in ranked if not show_topics(ent, kv[0])]))
    return [g for g in groups if g[2]]


def tag_links(name: str, ent: ents.Entities) -> str:
    return " · ".join(f'<a href="/shows/?topic={esc(t)}#{esc(t)}">{esc(ent.topic_names[t])}</a>' for t in show_topics(ent, name))


SHOWS_JS = """<script>(()=>{const bs=[...document.querySelectorAll('.topics button')],secs=[...document.querySelectorAll('[data-sec]')],
on=new Set((new URLSearchParams(location.search).get('topic')||'').split(',').filter(Boolean));
function paint(){bs.forEach(b=>b.setAttribute('aria-pressed',on.has(b.dataset.t)));secs.forEach(s=>s.classList.toggle('topic-off',on.size>0&&!on.has(s.dataset.t)));
const u=new URL(location);on.size?u.searchParams.set('topic',[...on].join(',')):u.searchParams.delete('topic');history.replaceState(null,'',u)}
bs.forEach(b=>b.addEventListener('click',()=>{on.has(b.dataset.t)?on.delete(b.dataset.t):on.add(b.dataset.t);paint()}));paint()})()</script>"""


def shows_index(shows: dict, ent: ents.Entities) -> str:
    """Every show under each of its topics, with a lens bar and topic buttons that narrow the page (several topics add up)."""
    groups = tag_groups(shows, ent)
    have = {t for t, _, _ in groups}
    btns = ""
    for g in ent.groups + [{"name": "", "topics": ["other"]}]:
        ts = [t for t in g["topics"] if t in have]
        if ts:
            btns += (f'<li class="grp">{esc(g["name"])}</li>' if g["name"] else "") + "".join(
                f'<li><button type="button" data-t="{esc(t)}" aria-pressed="false">{esc(dict(ent.topic_names, other="Other")[t])}</button></li>' for t in ts)
    body = f'<h1>Shows</h1>{lens_bar(ent)}<ul class="topics" aria-label="Topics">{btns}</ul>'
    for t, label, rows in groups:
        chips = "".join(f'<li class="lf" data-l="{esc(" ".join(ents.lenses_of(ent, show_topics(ent, s), [], 0)))}">'
                        f'<a class="chip" href="{esc(show_path(s))}">{esc(s)}</a>'
                        f'<span class="ct">{sum(len(e["claims"]) for e in eps)}</span></li>' for s, eps in rows)
        body += f'<section data-sec data-t="{esc(t)}"><h2 id="{esc(t)}">{esc(label)}</h2><ul class="tickers">{chips}</ul></section>'
    return page(f"Shows · {SITE}", body + SHOWS_JS, "shows", md="/shows.md", updated=newest_of(*(eps[0]["date"] for eps in shows.values())))


def show_page(name: str, eps: list[dict], ent: ents.Entities) -> str:
    links = tag_links(name, ent)
    sub = f'<p class="meta">{links}</p>' if links else ""
    body = "".join(episode_entry(e, i) for i, e in enumerate(eps))
    return page(f"{name} · {SITE}", f'<h1>{esc(name)}</h1>{sub}{body}', "shows", md=md_of(show_path(name)), updated=eps[0]["date"])


# ---------------------------------------------------------------- companies and Find

CREATOR_MAX = 200  # newest items listed on a creator's page


def x_views(published: Path) -> dict[str, list[dict]]:
    """X handle (lower case) -> its labelled posts that hold a view (a stance other than 0): id, handle, date and the tickers,
    newest first. Posts are the board's items (a thread is its first post), so a page and the Sentiment page list the same ones."""
    labels = stance.labelled(published)
    in_thread = {i for ids in stance.threads_recorded(published).values() for i in ids}
    out: dict[str, list[dict]] = {}
    seen = set()
    for _, rows in sorted(stance.post_rows(published).items(), reverse=True):
        for r in rows:
            handle, post_id = str(r["handle"]), str(r["id"])
            labs = [lab["ticker"] for lab in labels.get(r["key"], []) if lab.get("stance")]
            if r["key"] in seen or post_id in in_thread or not labs or not board.HANDLE.fullmatch(handle) or not post_id.isdigit():
                continue
            seen.add(r["key"])
            out.setdefault(handle.lower(), []).append({"id": post_id, "handle": handle, "date": str(r["date"])[:10], "tickers": labs})
    for rows in out.values():
        rows.sort(key=lambda p: (p["date"], p["id"]), reverse=True)
    return out


def creator_items(c: creators.Creator, ireg: dict, views: dict, show_owner: dict) -> tuple[list[dict], list[dict]]:
    """(videos, posts) of one creator: Social episodes of its sources' shows, and the posts of its handles that hold a view."""
    eps = [e for e in ireg.values() if isinstance(e.get("score"), int) and e["score"] >= MIN_SCORE
           and show_owner.get(norm_show(e.get("show"))) == c.id]
    posts = [p for h in c.x for p in views.get(h.lower(), [])]
    return eps, posts


def view_chips(syms: list[str], have: dict) -> str:
    """Chips for a post's tickers: the ticker page when it has one (`have`: normalized ticker -> the symbol its page is under),
    else plain text; a market target by its name."""
    out = []
    for t in dict.fromkeys(syms):
        name = board.MARKET_LINES[t][0] if t in board.MARKET_LINES else t
        out.append(f'<a class="chip" href="{esc(ticker_path(have[t]))}">{esc(t)}</a>' if t in have else f'<span class="chip">{esc(name)}</span>')
    return "".join(out)


def view_entry(p: dict, have: dict) -> str:
    """One X post with a view, as a row like a video's: a link to the post, the date and the tickers."""
    return (f'<li class="entry" data-d="{esc(p["date"])}"><div><h3><a href="https://x.com/{esc(p["handle"])}/status/{esc(p["id"])}" '
            f'rel="noopener noreferrer">@{esc(p["handle"])} on X</a></h3>'
            f'<div class="meta">{x_mark()}{esc(human_date(p["date"]))} · <span class="cos">{view_chips(p["tickers"], have)}</span></div></div></li>')


def creator_page(c: creators.Creator, eps: list[dict], posts: list[dict], have: dict) -> str:
    """A creator's videos and X posts with a view, newest first. No rating of the creator: the rows carry only what was said."""
    rows = sorted([(e["date"], e["id"], top_entry({**e, "_show_path": ""})) for e in eps]
                  + [(p["date"], p["id"], view_entry(p, have)) for p in posts], reverse=True)[:CREATOR_MAX]
    return page(f"{c.name} · {SITE}", f'<h1>{esc(c.name)}</h1><ol class="top">{"".join(r[2] for r in rows)}</ol>', "social",
                f"Videos and X posts from {c.name}.", md=md_of(creator_path(c.id)), updated=rows[0][0] if rows else "")


def creator_md(c: creators.Creator, eps: list[dict], posts: list[dict]) -> str:
    items = sorted([(e["date"], e["id"], f"- {mlink(e.get('title') or e['id'], e.get('youtube_url') or e.get('url'))} — {mt(e['show'])}, {e['date']}")
                    for e in eps]
                   + [(p["date"], p["id"], f"- {mlink('@' + p['handle'] + ' on X', 'https://x.com/%s/status/%s' % (p['handle'], p['id']))}"
                       f" — {p['date']}, {mt(', '.join(dict.fromkeys(p['tickers'])))}") for p in posts], reverse=True)[:CREATOR_MAX]
    return doc([f"# {mt(c.name)}", "", f"{plural(len(eps), 'video')} and {plural(len(posts), 'X post')} with a view, newest first. "
                f"[HTML]({absu(creator_path(c.id))}) · [{FEED_NAME}]({absu(md_of('/index.md'))})", "", NOTE, "", *(i[2] for i in items)])


def company_label(c: dict) -> str:
    return " · ".join(x for x in [c["kind"].capitalize(), c.get("ticker") or ""] if x)


def companies_chips(cos: dict, ent: ents.Entities) -> str:
    chips = "".join(
        f'<li class="lf" data-l="{esc(" ".join(c["lenses"]))}"><a class="chip" href="{esc(company_path(c["id"]))}">{esc(c["name"])}</a>'
        f'<span class="ct">{len(c["episodes"])}</span></li>'
        for c in sorted(cos.values(), key=lambda c: (-len(c["episodes"]), c["name"].lower())))
    return f'{lens_bar(ent)}<ul class="tickers" style="margin-top:18px">{chips}</ul>'


def why_of(ed: dict) -> str:
    bits = (["named in the title"] if ed["title"] else []) + (["their people spoke"] if ed["guest"] else []) \
        + ([plural(ed["claims"], "claim")] if ed["claims"] else [])
    return ", ".join(bits)


def company_page(c: dict, ent: ents.Entities, pub: dict) -> str:
    marks = "".join(lens_mark(ent, lid) for lid in c["lenses"])
    tk = c.get("ticker")
    tlink = f' · <a href="{esc(ticker_path(tk))}">{esc(tk)} claims</a>' if tk and tk in pub else ""
    sub = f'<p class="meta">{marks}{esc(c["kind"].capitalize())}{tlink}</p>'
    ppl = " · ".join(f'<a href="{esc(person_path(p["slug"]))}">{esc(p["name"])}</a>' + (f' ({esc(p["role"])})' if p["role"] else "")
                     for p in c["people"].values())
    people = f'<p class="meta">People: {ppl}</p>' if ppl else ""
    eps = "".join(top_entry(e, why=why_of(ed)) for e, ed in c["episodes"])
    claims = "".join(claim_li(x, show_ep=True) for x in c["claims"])
    body = (f'<h1>{esc(c["name"])}</h1>{sub}{people}'
            f'<h2>Episodes</h2><ol class="top" style="margin-top:0">{eps}</ol>'
            + (f'<h2>Claims</h2><ul class="claims">{claims}</ul>' if claims else ""))
    return page(f"{c['name']} · {SITE}", body, "tags", md=md_of(company_path(c["id"])), updated=c["episodes"][0][0]["date"])


def tags_page(pub: dict, people: dict, cos: dict, ent: ents.Entities) -> str:
    """Every ticker, person and company with a page, as three sections under a row of jump links. Each list is the one its own page used to show."""
    secs = ((TICKERS_NAME, "tickers", tickers_chips(pub)), ("People", "people", people_chips(people)),
            ("Companies", "companies", companies_chips(cos, ent)))
    jump = " · ".join(f'<a href="#{k}">{esc(n)}</a>' for n, k, _ in secs)
    body = f'<h1>{TAGS_NAME}</h1><p class="meta">{jump}</p>' + "".join(f'<section id="{k}"><h2>{esc(n)}</h2>{h}</section>' for n, k, h in secs)
    dates = [claim_date(c) for v in pub.values() for c in v] + [claim_date(c) for p in people.values() for c in p["claims"]] \
        + [c["episodes"][0][0]["date"] for c in cos.values()]
    return page(f"{TAGS_NAME} · {SITE}", body, "tags", md=md_of(TAGS_PATH), updated=newest_of(*dates))


def redirect_page(to: str, label: str, md: str) -> str:
    """A stand-in for a page that moved: refreshes to `to`, names it in a link, and asks search engines to forget the old address."""
    return ('<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(label)} · {SITE}</title><meta name="robots" content="noindex">'
            f'<meta http-equiv="refresh" content="0; url={esc(to)}"><link rel="canonical" href="{esc(absu(to.split("#")[0]))}">'
            f'<link rel="alternate" type="text/markdown" href="{esc(md)}"></head><body><p><a href="{esc(to)}">{esc(label)}</a></p></body></html>\n')


def find_index(reg: dict, ent: ents.Entities, cos: dict) -> dict:
    """What the Find page filters in the browser: one short row per episode with a page, newest first, plus name tables. A row is
    about 1 KB and the browser downloads the whole file: split it by month once it passes about 1.5 MB gzipped."""
    eps, people = [], {}
    for e in sorted(reg.values(), key=lambda e: (e["date"], e["id"]), reverse=True):
        if not e["page"]:
            continue
        for p in e["people"]:
            people[p["slug"]] = p["name"]
        eps.append({"i": e["page"], "t": e.get("title") or e["id"], "s": e.get("show") or "", "d": e["date"], "r": e.get("score"),
                    "c": list(e["edges"]), "p": [p["slug"] for p in e["people"]], "o": e["topics"], "l": e["lenses"],
                    "x": " ".join(c.get("text") or "" for c in e["claims"])[:800]})
    used = {c for x in eps for c in x["c"]}
    return {"topics": {t: n for t, n in ent.topic_names.items()},
            "lenses": {k: {"name": v.get("name") or k, "mark": v.get("mark") or k, "about": v.get("about") or ""} for k, v in ent.lenses.items()},
            "companies": {k: cos[k]["name"] for k in used if k in cos}, "people": people, "eps": eps}


FIND_JS = """<script>(async()=>{const $=id=>document.getElementById(id),P=new URLSearchParams(location.search),L=()=>window.sigmaLens?sigmaLens.get():'';
let D;try{D=await(await fetch('/find-index.json')).json()}catch(e){$('f-count').textContent='The index did not load. Try again later.';return}
const E=D.eps;E.forEach(e=>{e.h=[e.t,e.s,...e.p.map(p=>D.people[p]||''),...e.c.map(c=>D.companies[c]||''),e.x].join(' ').toLowerCase()});
const MO=['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];const byName=m=>Object.entries(m).sort((a,b)=>a[1].localeCompare(b[1]));
function fill(id,pairs){const s=$(id);pairs.forEach(([v,n])=>{const o=document.createElement('option');o.value=v;o.textContent=n;s.append(o)})}
fill('f-topic',Object.entries(D.topics));fill('f-company',byName(D.companies));fill('f-person',byName(D.people));
fill('f-show',[...new Set(E.map(e=>e.s).filter(Boolean))].sort((a,b)=>a.localeCompare(b)).map(s=>[s,s]));
const F={q:'f-q',topic:'f-topic',company:'f-company',person:'f-person',show:'f-show',days:'f-days',min:'f-min'};
for(const[k,id]of Object.entries(F))if(P.has(k))$(id).value=P.get(k);
const STEP=50;let hits=[],n=0;
function row(e){const li=document.createElement('li'),d=document.createElement('div'),h=document.createElement('h3'),a=document.createElement('a'),m=document.createElement('div');
li.className='entry';a.href=e.i;a.textContent=e.t;h.append(a);m.className='meta';
e.l.forEach(l=>{const k=document.createElement('span');k.className='mark '+l;k.textContent=(D.lenses[l]||{}).mark||l;const L=D.lenses[l]||{},t=(L.name||l)+': '+(L.about||'');k.dataset.tip=t;k.setAttribute('aria-label',t);k.setAttribute('role','img');k.tabIndex=0;m.append(k)});
m.append([e.s,e.d&&(MO[+e.d.slice(5,7)-1]+' '+(+e.d.slice(8))+', '+e.d.slice(0,4))].filter(Boolean).join(' \u00b7 '));
if(e.r){const b=document.createElement('span');b.className='meter';b.style.setProperty('--n',e.r);b.setAttribute('role','img');const h='Rated '+e.r+' out of 10.';b.dataset.tip=h;b.tabIndex=0;b.setAttribute('aria-label',h);m.prepend(b)}
d.append(h,m);
if(e.c.length){const w=document.createElement('div');w.className='meta';e.c.slice(0,6).forEach(c=>{const x=document.createElement('a');x.className='chip';x.href='/companies/'+encodeURIComponent(c);x.textContent=D.companies[c]||c;w.append(x,' ')});d.append(w)}
li.append(d);return li}
function more(){const out=$('f-out');hits.slice(n,n+STEP).forEach(e=>out.append(row(e)));n=Math.min(n+STEP,hits.length);$('f-more').hidden=n>=hits.length}
function run(){const v=k=>$(F[k]).value,q=v('q').trim().toLowerCase().split(/\\s+/).filter(Boolean),l=L(),
cut=+v('days')?new Date(Date.now()-v('days')*864e5).toISOString().slice(0,10):'',min=+v('min');
hits=E.filter(e=>(!v('topic')||e.o.includes(v('topic')))&&(!v('company')||e.c.includes(v('company')))&&(!v('person')||e.p.includes(v('person')))&&
(!v('show')||e.s===v('show'))&&(!l||e.l.includes(l))&&e.d>=cut&&(e.r||0)>=min&&q.every(w=>e.h.includes(w)));
n=0;$('f-out').textContent='';more();$('f-count').textContent=hits.length+(hits.length===1?' episode':' episodes');
const u=new URL(location);u.search='';for(const k of Object.keys(F)){const x=v(k);if(x&&x!=='0')u.searchParams.set(k,x)}if(l)u.searchParams.set('lens',l);history.replaceState(null,'',u)}
Object.values(F).forEach(id=>$(id).addEventListener('input',run));$('f-more').addEventListener('click',more);document.addEventListener('sigma-lens',run);run()})()</script>"""

NOTICE_PATH = "/notice/"
NOTICE = [  # the site's legal notice, one paragraph each; linked from every footer
    "Sigma summarizes public material and publishes research on methods and tools. It does not provide personalized advice.",
    "Summaries and calculations can be wrong. Check the linked source before relying on them.",
    "Sources retain rights to their work. Sigma links to source material and displays only the excerpts needed to identify a claim.",
    "This site may use privacy-preserving page-view analytics when enabled by its operator.",
]


def notice_page() -> str:
    body = "<h1>Notice</h1>" + "".join(f"<p>{esc(t)}</p>" for t in NOTICE)
    return page(f"Notice · {SITE}", body, "", "Opinions, not investment advice.", md=md_of(NOTICE_PATH))


def notice_md() -> str:
    return doc(["# Notice", "", *(x for t in NOTICE for x in (t, ""))])



def find_page(ent: ents.Entities, updated: str = "") -> str:
    sel = lambda id, label, opts="": f'<select id="{id}" aria-label="{label}"><option value="">{opts or label}</option></select>'
    body = ('<h1>Find</h1><h2>Episodes</h2><div class="facets"><input id="f-q" type="search" placeholder="Search titles, guests and claims" '
            'aria-label="Search titles, guests and claims" autocomplete="off"></div>' + lens_bar(ent) +
            '<div class="facets">' + sel("f-topic", "Topic", "Any topic") + sel("f-company", "Company", "Any company")
            + sel("f-person", "Person", "Any person") + sel("f-show", "Show", "Any show")
            + '<select id="f-days" aria-label="Time window"><option value="0">All time</option><option value="7">Past week</option>'
              '<option value="30">Past month</option><option value="90">Past 3 months</option></select>'
              f'<select id="f-min" aria-label="Rating"><option value="0">Any rating</option><option value="{MIN_SCORE}">Rated {MIN_SCORE}+</option>'
              '<option value="8">Rated 8+</option></select></div>'
            '<p class="meta" id="f-count" aria-live="polite"></p><ol class="top" id="f-out" style="margin-top:.6em"></ol>'
            '<button type="button" class="more-btn" id="f-more" hidden>Show more</button>'
            '<noscript><p>Search needs JavaScript. Browse <a href="/shows/">shows</a>, <a href="/tags/#companies">companies</a> or '
            '<a href="/tags/#people">people</a> instead.</p></noscript>' + FIND_JS)
    return page(f"Find · {SITE}", body, "find", "Search every episode by topic, company, person, show and lens.", md="/find.md", updated=updated)


def find_md(ent: ents.Entities) -> str:
    lenses = "; ".join(f"{mt(l.get('name') or k)} ({mt(l.get('about'))})" for k, l in ent.lenses.items())
    return doc(["# Find", "", "A page that filters every episode in the browser by text, topic, company, person, show, time window, "
                "rating and lens. It needs JavaScript; agents should read the data it filters instead.", "",
                f"- [find-index.json]({absu('/find-index.json')}): one row per episode with a page, newest first. Keys: `i` page path, `t` title, "
                "`s` show, `d` date, `r` rating out of 10 (or null), `c` company ids, `p` person slugs, `o` topic ids, `l` lens ids, `x` the claim text "
                "(first 800 characters). The tables `topics`, `lenses`, `companies` and `people` map ids to names.",
                f"- [companies.json]({absu('/companies.json')}), [people.json]({absu('/people.json')}), [shows.json]({absu('/shows.json')}): the same ids with page links.",
                f"- Lenses: {lenses or 'none'}."])


def episode_page(e: dict, ent: ents.Entities | None = None, cos: dict | None = None) -> str:
    title = e.get("title") or e["id"]
    t = ext_link(e.get("url"), title) or esc(title)
    meta = (rating_bar(e, influencer_hint(e["score"]) if e.get("influencer") else "") + e.get("_marks", "") + " · ".join(
        x for x in [show_name(e), esc(human_date(board.publication_day(e["published"]))) if e.get("published") else ""] if x) + listen_icons(e))
    kind = '<p class="meta">Rated as social commentary</p>' if e.get("influencer") else ""
    take = f'<p class="take">{esc(e["reason"])}</p>' if e.get("reason") and e["reason"] != title else ""
    chips = [f'<a class="chip" href="{esc(company_path(cid))}">{esc(cos[cid]["name"])}</a>' for cid in e.get("edges", {}) if cos and cid in cos]
    chips += [f'<a class="chip" href="/shows/?topic={esc(tp)}#{esc(tp)}">{esc(ent.topic_names[tp])}</a>' for tp in e.get("topics", []) if ent]
    about = f'<div class="meta">{" ".join(chips)}</div>' if chips else ""
    li = "".join(claim_li(c) for c in e["claims"])
    return page(f"{title} · {SITE}", f'<h1>{t}</h1><div class="meta">{meta}</div>{kind}{take}{about}'
                f'<ul class="claims{" influencer" if e.get("influencer") else ""}" style="margin-top:1.6em">{li}</ul>', "podcasts", md=md_of(e["page"]), updated=e["date"])


# ---------------------------------------------------------------- Markdown

def plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def mt(s) -> str:
    return re.sub(r"<(?=[A-Za-z/!?])", "\\\\<", " ".join(str(s if s is not None else "").split()))  # inert even if rendered


def ml(s) -> str:
    return mt(s).replace("[", "\\[").replace("]", "\\]")


def murl(u) -> str:
    return safe_url(u).replace(" ", "%20").replace("(", "%28").replace(")", "%29")


def mlink(label, url) -> str:
    u = murl(url)
    return f"[{ml(label)}]({u})" if u else ml(label)


def claim_md(c: dict) -> str:
    tail = []
    if c.get("speaker"):
        tail.append("**" + mt(c["speaker"]).replace("*", "") + "**")
    ts = fmt_ts(c.get("timestamp"))
    if ts:
        tail.append(mlink(ts, safe_url(c.get("link")) or safe_url(c.get("url"))))
    tk = []
    for t in c.get("tickers") or []:
        if isinstance(t, str) and t:
            tk.append(f"{ml(t[8:])} (private)" if is_private(t) else mlink(t, absu(ticker_path(t, "md"))))
    if tk:
        tail.append(" ".join(tk))
    return f"- {mt(c.get('text'))} — " + ", ".join(tail) if tail else f"- {mt(c.get('text'))}"


def episode_head_md(e: dict, level: int, self_page: bool = False) -> list[str]:
    title = mt(e.get("title") or e.get("id"))
    if e.get("page") and not self_page:
        heading = "#" * level + " " + mlink(title, absu(md_of(e["page"])))
    else:
        heading = "#" * level + " " + title
    meta = " · ".join(x for x in [mt(e.get("show")), human_date(board.publication_day(e["published"])) if e.get("published") else ""] if x)
    spotify = "Spotify (show)" if e.get("spotify_kind") == "show" else "Spotify"
    platforms = [(n, safe_url(u)) for n, u in [("YouTube", e.get("youtube_url")), ("Apple Podcasts", e.get("apple_url")), (spotify, e.get("spotify_url"))]]
    taken = {u for _, u in platforms if u}  # the episode and transcript links are dropped when they repeat one of these
    page_url, transcript = safe_url(e.get("url")), safe_url(e.get("transcript_url"))
    links = [mlink("Episode", page_url)] if page_url and page_url not in taken else []
    links += [mlink(n, u) for n, u in platforms if u]
    if transcript and transcript not in taken and transcript != page_url:
        links.append(mlink("Publisher transcript", transcript))
    out = [heading, ""]
    line = " · ".join(x for x in [meta] + links if x)
    if line:
        out += [line, ""]
    return out


def episode_block_md(e: dict, reg: dict, level: int, claims: list[dict] | None = None, take: str = "") -> list[str]:
    info = reg.get(e.get("id")) or {"id": e.get("id"), "title": e.get("title"), "show": e.get("show"), "published": e.get("published"),
                                    "url": e.get("url"), "transcript_url": e.get("transcript_url"), "page": "",
                                    **{k: e.get(k) for k in LINK_FIELDS}}
    out = episode_head_md(info, level)
    if take:
        out += [f"_{mt(take)}_", ""]
    out += [claim_md(c) for c in (e["claims"] if claims is None else claims)]
    return out + [""]


def grouped_md(claims: list[dict], reg: dict, level: int) -> list[str]:
    """Claims grouped under their episode, newest episode first."""
    groups: dict[str, list[dict]] = {}
    for c in newest_first(claims):
        groups.setdefault(c.get("episode_id") or "", []).append(c)
    out: list[str] = []
    for eid, cl in groups.items():
        info = reg.get(eid) or {"id": eid, "title": cl[0].get("title"), "show": cl[0].get("show"), "published": cl[0].get("published"),
                                "url": cl[0].get("url"), "page": "",
                                **{k: cl[0].get(k) for k in LINK_FIELDS}}
        out += episode_head_md(info, level)
        out += [claim_md(c) for c in sorted(cl, key=claim_ts)] + [""]
    return out


def doc(lines: list[str]) -> str:
    return "\n".join(lines).rstrip() + "\n"


NOTE = ("Claims are what a speaker said on a podcast, paraphrased and checked against the episode; they are not verified "
        "facts and not investment advice. Cite speaker, show, date and the timestamp link.")


def themes_json_md(r: dict) -> str:
    return f" · [Themes as JSON]({absu('/runs/' + quote(r['name']) + '/themes.json')})" if r.get("themes") else ""


def themes_md(r: dict, reg: dict, level: int) -> list[str]:
    """The week's themes as Markdown: the headline, then each theme with its summary and the claims that show it."""
    th = r.get("themes")
    if not th:
        return []
    out = ["#" * level + " Themes", ""]
    if th.get("headline"):
        out += [mt(th["headline"]), ""]
    for t in th["themes"]:
        out += ["#" * (level + 1) + " " + mt(t["title"]), ""]
        tickers = [x for x in t.get("tickers") or [] if isinstance(x, str) and x]
        tk = [f"{ml(x[8:])} (private)" if is_private(x) else mlink(x, absu(ticker_path(x, "md"))) for x in tickers]
        bits = [STANCES.get(t.get("stance"), ""), came_up_text(t), "Tickers: " + ", ".join(tk) if tk else ""]
        out += [" · ".join(b for b in bits if b), ""]
        if t.get("summary"):
            out += [mt(t["summary"]), ""]
        for ev in evidence_of(t):
            ep_page = (reg.get(ev.get("episode_id")) or {}).get("page")
            ts = fmt_ts(ev.get("timestamp"))
            who = "**" + mt(ev["speaker"]).replace("*", "") + "**" if ev.get("speaker") else ""
            title_md = mlink(ev["episode_title"], absu(md_of(ep_page)) if ep_page else "") if ev.get("episode_title") else ""
            where = ", ".join(x for x in [who, mt(ev.get("show")) if ev.get("show") else "",
                                          mlink(ts, ev.get("link")) if ts else "", title_md] if x)
            out.append(f"- {mt(ev.get('claim'))} — {where}" if where else f"- {mt(ev.get('claim'))}")
        out.append("")
    return out


def themes_index_md(runs: list[dict], reg: dict) -> str:
    out = ["# Themes", ""]
    for r in runs:
        if r.get("themes"):
            out += [f"## {mlink(issue_title(r), absu(run_md_path(r['name'])))}", ""] + themes_md(r, reg, 3)
    return doc(out)


def run_md(r: dict, reg: dict) -> str:
    title = issue_title(r)
    eps = shown(r)
    out = [f"# {title}", ""]
    jl = absu("/runs/" + quote(r["name"]) + "/claims.jsonl")
    out += [f"{'Weekly' if r['kind'] == 'weekly' else 'Daily'} issue: {plural(len(eps), 'episode')}, {plural(len(r['claims']), 'claim')}. "
            f"[This issue as JSONL]({jl}){themes_json_md(r)} · [Site index]({absu('/llms.txt')})", "", NOTE, ""]
    out += themes_md(r, reg, 2)
    for e in eps:
        take = e["reason"] if e.get("reason") and e["reason"] != e.get("title") else ""
        out += episode_block_md(e, reg, 2, take=take)
    return doc(out)


def ticker_md(sym: str, claims: list[dict], reg: dict, social: list[dict] = ()) -> str:
    claims = sorted(claims, key=lambda c: (claim_date(c), c.get("score") or 0), reverse=True)

    def count(cl):
        return f"{plural(len(cl), 'claim')} across {plural(len({c.get('episode_id') for c in cl}), 'episode')}, latest {max(claim_date(c) for c in cl)}"

    bits = ([count(claims)] if claims else []) + ([f"Social (influencer episodes): {count(list(social))}"] if social else [])
    out = [f"# {sym}", "", ". ".join(bits) + f". [HTML]({absu(ticker_path(sym))}) · [All tickers]({absu(md_of(TAGS_PATH))})", "", NOTE, ""]
    out += grouped_md(claims, reg, 2)
    return doc(out + (["## Social", ""] + grouped_md(list(social), reg, 3) if social else []))


def person_md(p: dict, reg: dict) -> str:
    roles = roles_of(p)
    n_ep = len({c.get("episode_id") for c in p["claims"]})
    latest = max(claim_date(c) for c in p["claims"])
    out = [f"# {p['name']}", ""]
    if roles:
        out += [f"Role: {'; '.join(mt(r) for r in roles)}", ""]
    out += [f"{plural(len(p['claims']), 'claim')} across {plural(n_ep, 'episode')}, latest {latest}. [HTML]({absu(person_path(p['slug']))}) · "
            f"[All people]({absu('/people.md')})", "", NOTE, ""]
    return doc(out + grouped_md(p["claims"], reg, 2))


def show_md(name: str, eps: list[dict], reg: dict, ent: ents.Entities) -> str:
    n = sum(len(e["claims"]) for e in eps)
    out = [f"# {mt(name)}", ""]
    if show_topics(ent, name):
        out += [f"Topics: {', '.join(ent.topic_names[t] for t in show_topics(ent, name))}", ""]
    out += [f"{plural(n, 'claim')} across {plural(len(eps), 'episode')}, latest {eps[0]['date']}. "
            f"[HTML]({absu(show_path(name))}) · [All shows]({absu('/shows.md')})", "", NOTE, ""]
    for e in eps:
        out += episode_block_md(e, reg, 2)
    return doc(out)


def shows_md(shows: dict, ent: ents.Entities) -> str:
    out = ["# Shows", "", f"Shows with at least one claim, grouped by topic (a show can have several), most claims first. "
           f"[JSON]({absu('/shows.json')}).", ""]
    for _, label, rows in tag_groups(shows, ent):
        out += [f"## {label}", ""]
        out += [f"- {mlink(s, absu(show_path(s, 'md')))}: {plural(len(eps), 'episode')}, "
                f"{plural(sum(len(e['claims']) for e in eps), 'claim')}, latest {eps[0]['date']}" for s, eps in rows]
        out.append("")
    return doc(out)


def company_md(c: dict, reg: dict, ent: ents.Entities) -> str:
    out = [f"# {mt(c['name'])}", "", f"{c['kind'].capitalize()}" + (f", ticker {mt(c['ticker'])}" if c.get("ticker") else "")
           + (f". Lenses: {', '.join(ent.lenses[l]['name'] for l in c['lenses'] if l in ent.lenses)}" if c["lenses"] else "") + ".", ""]
    if c["people"]:
        out += ["People: " + "; ".join(mlink(p["name"], absu(person_path(p["slug"], "md"))) + (f" ({mt(p['role'])})" if p["role"] else "")
                                       for p in c["people"].values()), ""]
    out += [f"{plural(len(c['episodes']), 'episode')}, {plural(len(c['claims']), 'claim')}, latest {c['episodes'][0][0]['date']}. "
            f"[HTML]({absu(company_path(c['id']))}) · [All companies]({absu('/companies.md')})", "", NOTE, "", "## Episodes", ""]
    for e, ed in c["episodes"]:
        t = mt(e.get("title") or e["id"])
        out.append(f"- {mlink(t, absu(md_of(e['page'])))} — {mt(e['show'])}, {e['date']} ({why_of(ed)})")
    return doc(out + ([""] + ["## Claims", ""] + grouped_md(c["claims"], reg, 3) if c["claims"] else []))


def companies_lines(cos: dict, h: int = 1) -> list[str]:
    out = [f"{'#' * h} Companies", "", "Companies the episodes are about: named in two or more claims or in the title, or the employer of a "
           f"speaker, most episodes first. [JSON]({absu('/companies.json')}).", ""]
    for c in sorted(cos.values(), key=lambda c: (-len(c["episodes"]), c["name"].lower())):
        out.append(f"- {mlink(c['name'], absu(company_path(c['id'], 'md')))}: {plural(len(c['episodes']), 'episode')}, latest {c['episodes'][0][0]['date']}")
    return out


def companies_md(cos: dict) -> str:
    return doc(companies_lines(cos))


def episode_md(e: dict) -> str:
    out = episode_head_md(e, 1, self_page=True)
    issues = ", ".join(mlink(issue_name, absu(run_md_path(issue_name))) for issue_name in e["runs"])
    rated = f"Rated {e['score']}/10 as social commentary. " if e.get("influencer") else ""
    out += [f"{rated}{plural(len(e['claims']), 'claim')}. Issues: {issues}. [HTML]({absu(e['page'])})", "", NOTE, ""]
    return doc(out + [claim_md(c) for c in e["claims"]])


def tickers_lines(pub: dict, h: int = 1) -> list[str]:
    out = [f"{'#' * h} {TICKERS_NAME}", "", "Public tickers mentioned in claims, most claims first. One Markdown page per ticker; "
           f"[JSON]({absu('/tickers.json')}).", ""]
    for t, v in sorted(pub.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out.append(f"- {mlink(t, absu(ticker_path(t, 'md')))}: {plural(len(v), 'claim')}, latest {max(claim_date(c) for c in v)}")
    return out


def tags_md(pub: dict, people: dict, cos: dict) -> str:
    """The three lists the Tags page shows, one Markdown file."""
    return doc([f"# {TAGS_NAME}", "", f"The ranked board is at [{SENTIMENT_NAME}]({absu(md_of(SENTIMENT_PATH))}).", ""]
               + tickers_lines(pub, 2) + [""] + people_lines(people, 2) + [""] + companies_lines(cos, 2))


def people_lines(people: dict, h: int = 1) -> list[str]:
    out = [f"{'#' * h} People", "", "Speakers with a name, most claims first. Unnamed speakers (host, guest, unknown) are not listed; "
           f"their claims are in the episode pages. [JSON]({absu('/people.json')}).", ""]
    for p in sorted(people.values(), key=lambda p: (-len(p["claims"]), p["name"])):
        roles = roles_of(p)
        role = f" ({mt(roles[0])})" if roles else ""
        out.append(f"- {mlink(p['name'], absu(person_path(p['slug'], 'md')))}{role}: {plural(len(p['claims']), 'claim')}, "
                   f"latest {max(claim_date(c) for c in p['claims'])}")
    return out


def people_md(people: dict) -> str:
    return doc(people_lines(people))


def episodes_md(reg: dict) -> str:
    out = ["# Episodes", "", f"Every episode considered across issues; those with claims link to a page. [JSON]({absu('/episodes.json')}).", ""]
    for e in sorted(reg.values(), key=lambda e: (e["date"], e["id"]), reverse=True):
        t = mt(e["title"] or e["id"])
        head = mlink(t, absu(md_of(e["page"]))) if e["page"] else ml(t)
        out.append(f"- {head} — {mt(e['show'])}, {e['date']}, {plural(len(e['claims']), 'claim')}")
    return doc(out)


def social_md(ireg: dict, eds: list[dict] | None = None) -> str:
    eps = social_episodes(ireg)
    out = ["# Social", "", f"Videos from creators who pick stocks, rated {MIN_SCORE} or higher, newest first ({plural(len(eps), 'episode')}). They are rated on their calls and the "
           f"evidence behind them, apart from the interview ranking. [HTML]({absu(SOCIAL_PATH)}) · [Site index]({absu('/llms.txt')})"
           + (f" · The other side of Social: [X]({absu('/x.md')})" if eds else ""), "", NOTE, ""]
    for e in eps:
        out += episode_block_md(e, ireg, 2, take=f"Rated {e['score']}/10 as social commentary. {e.get('reason') or ''}".strip())
    return doc(out)


def index_md(runs: list[dict], reg: dict, pub: dict, people: dict, ireg: dict | None = None, eds: list[dict] | None = None,
             signals: dict | None = None) -> str:
    out = ["# Sigma", "", "> " + SUMMARY, "", NOTE, "",
           f"Machine-readable index: [llms.txt]({absu('/llms.txt')}). Everything in one file: [llms-full.txt]({absu('/llms-full.txt')}).", ""]
    if signals:
        out += [f"Market signals, every day: [Signals]({absu('/signals.md')}) ([index.json]({absu('/signals/index.json')})).", ""]
    if runs:
        out += ["## Browse", "", f"- [Themes]({absu('/themes.md')})", f"- [Shows]({absu('/shows.md')})", f"- [Companies]({absu('/companies.md')})", f"- [{SENTIMENT_NAME}]({absu(md_of(SENTIMENT_PATH))}): the ranked board", f"- [{TAGS_NAME}]({absu(md_of(TAGS_PATH))}) ({len(pub)} tickers)", f"- [People]({absu('/people.md')}) ({len(people)})",
                f"- [Episodes]({absu('/episodes.md')}) ({len(reg)})"] \
            + [f"- [{FEED_NAME}]({absu('/index.md')}): selected podcast episodes and creator videos, newest first"] \
            + ([f"- [{X_NAME}]({absu('/x.md')}): the day's edition from the X accounts Sigma follows"] if eds else []) + ["", "## Issues", ""]
        out += [f"- {mlink(issue_title(r), absu(run_md_path(r['name'])))}: {plural(len(shown(r)), 'episode')}, {plural(len(r['claims']), 'claim')}"
                for r in runs]
        top = feed_rows(reg, ireg)
        if top:
            out += ["", f"## {FEED_NAME}", ""]
            for e in top:
                title = mlink(e["title"] or e["id"], absu(md_of(e["page"])) if e.get("page") else e.get("url"))
                platform = "YouTube" if e.get("influencer") else "Podcast"
                published = e.get("published") or e.get("date")
                out.append(f"- {platform}: {title}, {mt(e.get('show'))}, {mt(published)}" + (f": {mt(e['reason'])}" if e.get("reason") else ""))
        if wk := [r for r in runs if r["kind"] == "weekly"][:1]:
            out += ["", f"## Latest weekly: {issue_title(wk[0])}", ""]
            out += themes_md(wk[0], reg, 3)
            for e in shown(wk[0]):
                take = e["reason"] if e.get("reason") and e["reason"] != e.get("title") else ""
                out += episode_block_md(e, reg, 3, take=take)
    return doc(out)


SUMMARY = "What the people who move markets are saying, every claim traced to its source."


def llms_txt(runs: list[dict], reg: dict, pub: dict, people: dict, ireg: dict | None = None, eds: list[dict] | None = None,
             signals: dict | None = None) -> str:
    top_t = sorted(pub.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:15]
    top_p = sorted(people.values(), key=lambda p: (-len(p["claims"]), p["name"]))[:15]
    n_claims = sum(len(r["claims"]) for r in runs)
    out = ["# Sigma", "", "> " + SUMMARY, "",
           f"{plural(len(runs), 'issue')}, {plural(len(reg), 'episode')}, {plural(n_claims, 'claim')} so far. A claim is one falsifiable sentence, paraphrased from "
           "the episode, with the speaker, tickers and a link that opens the episode at that moment (YouTube when known). "
           "Claims are what a speaker said, not verified facts and not investment advice; cite speaker, show, date and the link.", "",
           "How to use: for a broad question read all of llms-full.txt. For one ticker open /tickers/SYM.md "
           "(for example /tickers/NVDA.md). For one person open /people/first-last.md (names are in people.json). "
           "For one show open its `md` link in shows.json. For a date "
           "range or any other filter, load claims.jsonl and filter on `date`, `tickers`, `person`, `show`. Every HTML page has "
           "a Markdown twin at the same path ending in `.md`. The same moment can appear in a daily and a weekly issue; "
           "ticker, person and episode pages already drop the repeats, the issue pages and claims.jsonl do not. "
                      "A weekly issue opens with its themes: a headline and 3-5 cross-episode themes, each with a stance (consensus, split or "
           "emerging), tickers, how many episodes it came up in, and the cited claims. They are at the top of the issue's Markdown "
           "page and in llms-full.txt; as JSON at /runs/<issue>/themes.json.", "",
           "## Start here", "",
           f"- [llms-full.txt]({absu('/llms-full.txt')}): every claim from every issue as Markdown, newest first, grouped by issue and episode",
           f"- [claims.jsonl]({absu('/claims.jsonl')}): one claim per line with id, text, speaker, person, role, show, date, tickers, link, youtube_url, apple_url, spotify_url, page URLs",
           f"- [Home]({absu('/index.md')}): " + "the newest selected podcast and YouTube episodes, followed by the latest weekly issue", ""]
    if signals:
        from . import signals_site
        out += signals_site.llms_section(signals)
    if runs:
        out += ["## Issues", ""]
        out += [f"- [{issue_title(r)}]({absu(run_md_path(r['name']))}): {r['kind']}, {plural(len(shown(r)), 'episode')}, {plural(len(r['claims']), 'claim')} "
                f"([JSONL]({absu('/runs/' + quote(r['name']) + '/claims.jsonl')}){themes_json_md(r)})" for r in runs]
        out.append("")
    out += ["## Indexes", "",
            f"- [{SENTIMENT_NAME}]({absu(md_of(SENTIMENT_PATH))}): the market, rates and credit, then US-listed tickers, ranked by how bullish or bearish the sources are, recent items counting most, "
            f"each linking to its claims ([JSON]({absu('/tickers.json')}): all {len(pub)} symbols with claim counts)",
            f"- [{TAGS_NAME}]({absu(md_of(TAGS_PATH))}): every ticker, person and company with a page",
            f"- [People]({absu('/people.md')}): {len(people)} named speakers ([JSON]({absu('/people.json')}))",
            f"- [Episodes]({absu('/episodes.md')}): {len(reg)} episodes ([JSON]({absu('/episodes.json')}))",
            f"- [Shows]({absu('/shows.md')}): one page per show with its episodes and claims ([JSON]({absu('/shows.json')}))",
            f"- [Companies]({absu('/companies.md')}): the companies episodes are about, one page each with its episodes, claims and people ([JSON]({absu('/companies.json')}))",
            f"- [Find]({absu('/find/')}): filter every episode by topic, company, person, show and lens in the browser; the data is [find-index.json]({absu('/find-index.json')})",
            f"- [Issues]({absu('/runs.json')}): list of issues with claim counts (JSON)"]
    if ireg:
        out.append(f"- [{FEED_NAME}]({absu('/index.md')}): selected interviews and creator videos appear together, newest first")
    if eds:
        out.append(f"- [{SOCIAL_NAME} › {X_NAME}]({absu('/x.md')}): one edition a day from the X accounts Sigma follows, sentences citing the posts behind them "
                   f"([this week]({absu('/x/week.md')}), [archive]({absu('/x/archive.md')}), a day at /x/YYYY-MM-DD.md); the authors' claims, not verified")
    out.append("")
    if top_t:
        out += ["## Most-mentioned tickers", ""]
        out += [f"- [{t}]({absu(ticker_path(t, 'md'))}): {plural(len(v), 'claim')}" for t, v in top_t] + [""]
    if top_p:
        out += ["## Most-quoted people", ""]
        out += [f"- [{mt(p['name'])}]({absu(person_path(p['slug'], 'md'))}): {plural(len(p['claims']), 'claim')}" for p in top_p] + [""]
    out += ["## Optional", "",
            f"- [Sitemap]({absu('/sitemap.xml')})", ""]
    return doc(out)


def llms_full(runs: list[dict], reg: dict) -> str:
    out = ["# Sigma: all claims", "", "> " + SUMMARY, "", NOTE, "",
           f"Newest issue first; inside an issue, episodes in the issue's order, claims by speaker timestamp. Index: {absu('/llms.txt')}", ""]
    for r in runs:
        out += [f"## {issue_title(r)} ({r['name']})", ""]
        out += themes_md(r, reg, 3)
        for e in shown(r):
            out += episode_block_md(e, reg, 3)
    return doc(out)


# ---------------------------------------------------------------- JSON indexes

def dump(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def episode_json(e: dict) -> dict:
    return {"episode_id": e["id"], "title": e["title"], "show": e["show"], "published": e["published"], "url": e["url"],
            "youtube_url": e["youtube_url"], "apple_url": e["apple_url"], "spotify_url": e["spotify_url"],
            "spotify_kind": e["spotify_kind"], "transcript_url": e["transcript_url"], "claims": len(e["claims"]), "issues": e["runs"],
            "score": e["score"], "reason": e["reason"], "topics": e.get("topics", []), "companies": list(e.get("edges", {})),
            "lenses": e.get("lenses", []),
            "page": absu(e["page"]) if e["page"] else None, "md": absu(md_of(e["page"])) if e["page"] else None}


def shows_json(reg: dict, ent: ents.Entities) -> list[dict]:
    by: dict[str, list[dict]] = {}
    for e in reg.values():
        by.setdefault(e["show"] or "Unknown", []).append(e)
    out = []
    for show, eps in by.items():
        eps = sorted(eps, key=lambda e: (e["date"], e["id"]), reverse=True)
        out.append({"show": show, "episodes": [{"episode_id": e["id"], "title": e["title"], "published": e["published"],
                                                "claims": len(e["claims"]), "page": absu(e["page"]) if e["page"] else None}
                                               for e in eps],
                    "episode_count": len(eps), "claims": sum(len(e["claims"]) for e in eps),
                    "latest_date": eps[0]["date"] or None, "tags": show_topics(ent, show),
                    "lenses": ents.lenses_of(ent, show_topics(ent, show), [], 0),
                    "page": absu(show_path(show)) if any(e["claims"] for e in eps) and show != "Unknown" else None,
                    "md": absu(show_path(show, "md")) if any(e["claims"] for e in eps) and show != "Unknown" else None})
    return sorted(out, key=lambda s: (-s["claims"], s["show"]))


# ---------------------------------------------------------------- X (a third kind of source: one edition a day, with the posts behind it)

def x_mark() -> str:
    """The X tile, like a lens tile: it marks the X side of the YouTube | X switch."""
    return f'<span class="mark x" role="img" aria-label="X">{X_LOGO}</span>'


def annotate_posts(posts: list[dict], ent: ents.Entities, cos: dict, pub: dict) -> None:
    """Chips from a post's cashtags: the company page, else the ticker page, else plain text for a private name."""
    for p in posts:
        ids = [ents.resolve_ticker(ent, t)[0] for t in p["tickers"]]
        p["_chips"] = "".join(
            f'<a class="chip" href="{esc(company_path(cid))}">{esc(ents.resolve_ticker(ent, t)[1])}</a>' if cid in cos
            else f'<a class="chip" href="{esc(ticker_path(t))}">{esc(t)}</a>' if t in pub
            else f'<span class="chip">{esc(t[8:] if is_private(t) else t)}</span>' for t, cid in zip(p["tickers"], ids))


def post_entry(p: dict, n: int) -> str:
    """One cited post: the number the sentences cite it by, its author and tickers, then an empty slot that the page fills with X's embed as it scrolls near."""
    chips = f' <span class="cos">{p["_chips"]}</span>' if p["_chips"] else ""
    who = (f'<a href="{esc(p["_creator_path"])}">@{esc(p["handle"])}</a>' if p.get("_creator_path")  # a creator's page, which has the profile's posts
           else f'<a href="https://x.com/{esc(p["handle"])}" rel="noopener noreferrer">@{esc(p["handle"])}</a>')
    return (f'<li class="post lf" data-l="signals" id="p-{esc(p["id"])}">{f"<span class=n>{n}</span>" if n else ""}<div>'
            f'<div class="meta">{who}{chips}</div>'
            f'<div class="embed" data-href="https://twitter.com/{esc(p["handle"])}/status/{esc(p["id"])}"><a class="open" href="{esc(p["url"])}" rel="noopener noreferrer">Open on X</a></div>'
            f'</div></li>')


# Every X post is X's own embed (platform.twitter.com/widgets.js, do-not-track), loaded as it scrolls near the viewport: X shows the
# text, and a reader's browser contacts X only for posts it is about to show. The published edition carries no post text.
EMBED_JS = """<script>(()=>{const dark=()=>{const t=document.documentElement.dataset.theme;return t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme:dark)').matches)};
let widgets;function load(){return widgets||(widgets=new Promise((ok,no)=>{if(window.twttr&&window.twttr.widgets)return ok();const s=document.createElement('script');
s.src='https://platform.twitter.com/widgets.js';s.async=true;s.onload=ok;s.onerror=no;document.head.append(s)}))}
const io=new IntersectionObserver(es=>es.forEach(e=>{if(!e.isIntersecting)return;io.unobserve(e.target);const box=e.target,q=document.createElement('blockquote'),a=document.createElement('a');
q.className='twitter-tweet';q.dataset.dnt='true';q.dataset.theme=dark()?'dark':'light';a.href=box.dataset.href;a.className='open';a.textContent='Open on X';q.append(a);
load().then(()=>{box.textContent='';box.append(q);window.twttr.widgets.load(box)}).catch(()=>{})}),{rootMargin:'700px 0px'});
document.querySelectorAll('.embed').forEach(b=>io.observe(b))})()</script>"""


X_TABS = (("/x/", "Today", "today"), ("/x/week/", "This week", "week"), ("/x/archive/", "Archive", "archive"))
EDITION_NOTE = "Authors' claims, not verified, not advice."


def x_tabs(cur: str) -> str:
    on = ' aria-current="page"'
    return (f'{social_switch("x")}<nav class="xtabs" aria-label="X editions">'
            + "".join(f'<a href="{h}"{on if k == cur else ""}>{n}</a>' for h, n, k in X_TABS) + "</nav>")


def load_editions(published: Path) -> list[dict]:
    """published/x/editions/<date>.json, newest first. A sentence or post with a bad id or handle is dropped."""
    out = []
    for f in sorted((published / "x" / "editions").glob("*.json"), reverse=True) if (published / "x" / "editions").is_dir() else []:
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except ValueError:
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(e.get("date") or "")):
            continue
        ok = lambda p: re.fullmatch(r"[A-Za-z0-9_]{1,15}", str(p.get("handle") or "")) and str(p.get("id") or "").isdigit()
        posts = [p for p in e.get("posts") or [] if ok(p)]
        ids = {p["id"] for p in posts}
        blurb = lambda k: [{"theme": str(s.get("theme") or ""), "text": str(s["text"]), "cites": [c for c in s.get("cites") or [] if c in ids]}
                           for s in e.get(k) or [] if s.get("text")]
        card = lambda p: {"id": p["id"], "handle": p["handle"],
                          "tickers": [t.lstrip("$").upper() for t in p.get("cashtags") or [] if isinstance(t, str) and re.fullmatch(r"\$?[A-Za-z0-9.]{1,10}", t)],
                          "url": f"https://x.com/{p['handle']}/status/{p['id']}"}
        win = e.get("window")  # the scan window's end is the only time an edition file holds; a date alone when it is missing or unreadable
        end = str(win[-1]) if isinstance(win, list) and win and isinstance(win[-1], str) and len(win[-1]) > 10 else ""
        out.append({"date": e["date"], "at": end or e["date"], "headline": str(e.get("headline") or ""), "signals": blurb("signals"),
                    "accounts": e.get("accounts"), "posts_read": e.get("posts_read"),
                    "posts": [card(p) for p in posts], "more": [card(p) for p in e.get("more") or [] if ok(p) and p["id"] not in ids]})
    return out


def x_day_path(d: str) -> str:
    return f"/x/{d}/"


def themes_of(sentences: list[dict]) -> list[tuple[str, list[dict]]]:
    """Consecutive sentences grouped by their theme; an edition written before themes is one untitled group."""
    out: list[tuple[str, list[dict]]] = []
    for s in sentences:
        if out and out[-1][0] == s["theme"]:
            out[-1][1].append(s)
        else:
            out.append((s["theme"], [s]))
    return out


def blurb_html(ed: dict, ent: ents.Entities, base: str = "", h: int = 2, embeds: bool = False) -> str:
    """The sentences by lens, each ending in the numbers of its posts (anchors on this page, or on the day page when `base` is set).
    A themed edition reads as sections: the theme, its sentences as one paragraph, and with `embeds` the posts it cites, folded
    under "Show N posts" so a reader can move theme to theme; a check marks a theme read, folds it and moves to the next."""
    num = {p["id"]: i for i, p in enumerate(ed["posts"], 1)}
    post = {p["id"]: p for p in ed["posts"]}
    cite = lambda c: f'<a class="cite" href="{base}#p-{esc(c)}" aria-label="Post {num[c]} by @{esc(post[c]["handle"])}">{num[c]}</a>'
    out = ""
    for lens in ("signals",):
        if not ed[lens]:
            continue
        name = (ent.lenses.get(lens) or {}).get("name") or lens.upper()
        body = ""
        for k, (theme, ss) in enumerate(themes_of(ed[lens])):
            if not theme:
                body += '<ol class="blurb">' + "".join(f'<li>{esc(s["text"])}' + "".join(map(cite, s["cites"])) + "</li>" for s in ss) + "</ol>"
                continue
            shown = list(dict.fromkeys(c for s in ss for c in s["cites"]))
            done = (f'<button type="button" class="done" aria-pressed="false" aria-label="Mark read: {esc(theme)}">✓</button>'
                    if embeds else "")
            body += (f'<section class="theme" data-key="{esc(ed["date"])}:{lens}:{k}"><div class="thead"><h{h + 1}>{esc(theme)}</h{h + 1}>{done}</div>'
                     f'<p class="blurb">' + " ".join(esc(s["text"]) + "".join(map(cite, s["cites"])) for s in ss) + "</p>"
                     + (f'<details class="tposts"><summary>Show {len(shown)} post{"s" if len(shown) != 1 else ""}</summary>'
                        f'<ol class="posts">{"".join(post_entry(post[c], num[c]) for c in shown)}</ol></details>' if embeds else "")
                     + "</section>")
        out += (f'<div class="lf" data-l="{lens}"><h{h} class="lensname">{lens_mark(ent, lens, False) if lens in ent.lenses else ""}{esc(name)}</h{h}>'
                f'{body}</div>')
    return out + (THEME_JS if embeds and "data-key" in out else "")


# A theme's check folds it to its title and scrolls to the next unread one; the pick is kept per browser. A cite opens the
# folded posts it points into.
THEME_JS = """<script>(()=>{const P='sigma-read:',get=k=>{try{return localStorage.getItem(P+k)==='1'}catch(e){return false}},
put=(k,v)=>{try{v?localStorage.setItem(P+k,'1'):localStorage.removeItem(P+k)}catch(e){}};
const mark=(t,v)=>{t.classList.toggle('read',v);t.querySelector('.done').setAttribute('aria-pressed',v)};
document.querySelectorAll('.theme[data-key]').forEach(t=>{mark(t,get(t.dataset.key));t.querySelector('.done').addEventListener('click',()=>{
const v=!t.classList.contains('read');mark(t,v);put(t.dataset.key,v);if(!v)return;
const all=[...document.querySelectorAll('.theme[data-key]')].filter(x=>x.offsetParent),n=all.slice(all.indexOf(t)+1).find(x=>!x.classList.contains('read'));
(n||t).scrollIntoView({behavior:'smooth',block:'start'})})});
const open=h=>{const e=h&&document.getElementById(h.slice(1));const d=e&&e.closest('details');if(d)d.open=true};
document.addEventListener('click',e=>{const a=e.target.closest('a.cite');if(a)open(a.hash)});open(location.hash)})()</script>"""


def edition_meta(ed: dict) -> str:
    bits = [human_date(ed["date"], True)]
    if ed.get("accounts"):
        bits.append(f'{ed["accounts"]} accounts')
    if ed.get("posts_read"):
        bits.append(f'{ed["posts_read"]} posts read')
    return " · ".join(bits)


def edition_page(ed: dict, ent: ents.Entities, cur: str, lead: str = "") -> str:
    """`lead` is the day's Signals view (signals_site.lead), which these pages open with; the edition follows it under its own headline."""
    # a post a themed section already shows is not shown again under Posts
    inline = {c for s in ed["signals"] if s["theme"] for c in s["cites"]}
    posts = "".join(post_entry(p, i) for i, p in enumerate(ed["posts"], 1) if p["id"] not in inline)
    more = "".join(post_entry(p, 0) for p in ed["more"])
    h = "h2" if lead else "h1"
    body = (f'{x_tabs(cur)}{lead}<{h}>{esc(ed["headline"] or "X today")}</{h}><p class="meta">{esc(edition_meta(ed))}</p>{lens_bar(ent, False)}'
            f'{blurb_html(ed, ent, embeds=True)}<p class="meta note">{esc(EDITION_NOTE)}</p>'
            + (f'<div data-sec><h2>{"More posts" if inline else "Posts"}</h2><ol class="posts">{posts}</ol></div>' if posts else "")
            + (f'<div data-sec><h2>More from today</h2><ol class="posts more">{more}</ol></div>' if more else "") + EMBED_JS)
    return page(f"X {human_date(ed['date'])} · {SITE}", body, "social", ed["headline"] or "What the X accounts Sigma follows said today.",
                md="/x.md" if cur == "today" else md_of(x_day_path(ed["date"])), updated=ed["at"])


def edition_md(ed: dict, ent: ents.Entities, lead: str = "") -> str:
    num = {p["id"]: i for i, p in enumerate(ed["posts"], 1)}
    out = [lead] if lead else []
    out += [f"{'##' if lead else '#'} {ed['headline'] or 'X today'}", "", edition_meta(ed), "", EDITION_NOTE, ""]
    line = lambda p: mlink('@' + p['handle'], p['url']) + (f", {', '.join(mt(t) for t in p['tickers'])}" if p["tickers"] else "")
    for lens in ("signals",):
        if ed[lens]:
            out += [f"## {(ent.lenses.get(lens) or {}).get('name') or lens.upper()}", ""]
            for theme, ss in themes_of(ed[lens]):
                out += ([f"### {ml(theme)}", ""] if theme else [])
                out += [f"- {ml(s['text'])} " + " ".join(f"[{num[c]}]" for c in s["cites"]) for s in ss] + [""]
    out += ["## Posts", ""] + [f"{num[p['id']]}. {line(p)}" for p in ed["posts"]]
    if ed["more"]:
        out += ["", "## More from today", ""] + [f"- {line(p)}" for p in ed["more"]]
    return doc(out)


def week_page(eds: list[dict], ent: ents.Entities) -> str:
    days = "".join(f'<section class="day"><p class="date">{esc(human_date(e["date"], True))}</p>'
                   f'<h2 class="day-title"><a href="{x_day_path(e["date"])}">{esc(e["headline"] or "X today")}</a></h2>'
                   f'{blurb_html(e, ent, x_day_path(e["date"]), 3)}</section>' for e in eds)
    return page(f"X this week · {SITE}", f'{x_tabs("week")}{lens_bar(ent, False)}{days or "<p>No editions this week.</p>"}', "social",
                "The week on X: each day's edition.", md="/x/week.md", updated=eds[0]["at"] if eds else "")


def week_md(eds: list[dict]) -> str:
    out = ["# X this week", ""]
    for e in eds:
        out += [f"## {mlink(e['headline'] or e['date'], x_day_path(e['date']))}", "", edition_meta(e), ""]
        out += [f"- {ml(s['text'])}" for s in e["signals"]] + [""]
    return doc(out)


def archive_page(eds: list[dict]) -> str:
    rows = "".join(f'<li><a class="d" href="{x_day_path(e["date"])}">{esc(human_date(e["date"], True))}</a>'
                   f'<a href="{x_day_path(e["date"])}">{esc(e["headline"] or "X today")}</a></li>' for e in eds)
    return page(f"X archive · {SITE}", f'{x_tabs("archive")}<ul class="archive">{rows}</ul>', "social", "Every daily X edition.", md="/x/archive.md", updated=eds[0]["at"] if eds else "")


def archive_md(eds: list[dict]) -> str:
    return doc(["# X archive", ""] + [f"- {mlink(e['date'], x_day_path(e['date']))}: {ml(e['headline'])}" for e in eds])


# ---------------------------------------------------------------- build

def write(p: Path, s: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(s, encoding="utf-8")


def jsonl(claims: list[dict]) -> str:
    return "".join(json.dumps({k: v for k, v in c.items() if not k.startswith("_")}, ensure_ascii=False) + "\n" for c in claims)


AI_BOTS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot", "anthropic-ai",
           "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended", "CCBot", "cohere-ai", "Meta-ExternalAgent",
           "Amazonbot", "Bytespider"]


def robots_txt() -> str:
    blocks = ["User-agent: *\nAllow: /\n"] + [f"User-agent: {b}\nAllow: /\n" for b in AI_BOTS]
    return "\n".join(blocks) + f"\nSitemap: {absu('/sitemap.xml')}\n"


def sitemap_xml(entries: list[tuple]) -> str:
    rows = []
    for path, last in entries:
        lm = f"<lastmod>{esc(last)}</lastmod>" if last else ""
        rows.append(f"<url><loc>{esc(absu(path))}</loc>{lm}</url>")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
            + "\n".join(rows) + "\n</urlset>\n")


def research_index_page(posts: list[dict]) -> tuple[str, str]:
    if not posts:
        body = "<h1>Research</h1><p>No research is published yet.</p>"
        md = doc(["# Research", "", "No research is published yet."])
    else:
        rows = "".join(f'<li><span class="d">{esc(p["date"])}</span><a href="{public_research.post_path(p["slug"])}">{esc(p["title"])}</a>'
                       f'<p class="lede">{esc(p["summary"])}</p></li>' for p in posts)
        body = f'<h1>Research</h1><ul class="archive">{rows}</ul>'
        md = doc(["# Research", "", *[f"- {p['date']}: [{ml(p['title'])}]({absu(public_research.post_path(p['slug']))}) — {ml(p['summary'])}" for p in posts]])
    return page(f"Research · {SITE}", body, "research", "Research on methods and tools.", md=md_of("/research/")), md


def research_post_pages(posts: list[dict], emit, out: Path, sitemap: list[tuple]) -> None:
    public = []
    for post in posts:
        path = public_research.post_path(post["slug"])
        paragraphs = "".join(f"<p>{esc(block)}</p>" for block in re.split(r"\n\s*\n", post["body"].strip()) if block.strip())
        body = f'<p class="date">{esc(post["date"])}</p><h1>{esc(post["title"])}</h1><p class="lede">{esc(post["summary"])}</p>{paragraphs}'
        markdown = doc([f"# {post['title']}", "", post["date"], "", post["summary"], "", *post["body"].strip().splitlines()])
        emit(path, page(f"{post['title']} · {SITE}", body, "research", post["summary"], md=md_of(path), updated=post["date"]), markdown, post["date"])
        public.append({**post, "path": absu(path), "markdown": absu(md_of(path))})
        write(out / "research" / f"{post['slug']}.json", json.dumps(post, ensure_ascii=False, indent=1) + "\n")
        sitemap.append((f"/research/{post['slug']}.json", post["date"]))
    write(out / "research" / "index.json", json.dumps({"posts": public}, ensure_ascii=False, indent=1) + "\n")


def build(published: Path, out: Path, base_url: str | None = None, entities_file: Path | None = None) -> dict:
    global BASE_URL, SITE, MAKER, X_PROFILE, SITE_YEAR, DAILY_RUNS
    old = (BASE_URL, SITE, MAKER, X_PROFILE, SITE_YEAR, DAILY_RUNS)
    identity = load_site_identity()
    BASE_URL, SITE, MAKER, X_PROFILE = (base_url or identity.base_url).rstrip("/"), identity.name, identity.maker, identity.x_profile
    try:
        research_posts = public_research.load()
        return _build(published, out, entities_file or ENTITIES_FILE, research_posts)
    finally:
        BASE_URL, SITE, MAKER, X_PROFILE, SITE_YEAR, DAILY_RUNS = old


def show_styles(path: Path = SOURCES_FILE) -> dict[str, str]:
    """{show name or alias: its style in sources.yaml today}. A show's current style decides where all of its episodes appear,
    so changing it moves past episodes too. A show not listed keeps the kind it was scored as."""
    if not path.exists():
        return {}
    try:
        from .config import load_sources
    except ImportError:  # the site host builds with the standard library only; every source is one flow-style line
        out = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := re.match(r"\s*- \{.*?\bname: (\"[^\"]*\"|[^,}]+)", line):
                st = re.search(r"\bstyle: (\w+)", line)
                al = re.search(r"\baliases: \[([^\]]*)\]", line)
                names = re.findall(r'"([^"]*)"|([^,"]+)', al[1]) if al else []
                for n in [json.loads(m[1]) if m[1].startswith('"') else m[1], *(q or b for q, b in names)]:
                    out[norm_show(n.strip().strip('"'))] = st[1] if st else "interview"
        return out

    return {norm_show(n): s.style for s in load_sources(path)[0] for n in [s.name, *s.aliases]}


def _build(published: Path, out: Path, entities_file: Path, research_posts: list[dict] | None = None) -> dict:
    global SITE_YEAR
    from . import signals_site  # imports this module, so not at the top
    runs = load_runs(published)
    research_posts = research_posts or []
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    people = enrich(runs)
    reg = build_episodes(runs)
    style = show_styles()
    moved = {k: reg.pop(k) for k in [k for k, e in reg.items() if style.get(norm_show(e.get("show"))) == "influencer"]}  # a show now marked Social leaves Deep everywhere, back to its first episode; its Social score lists it
    pub = collect_tickers(runs)[0]
    shows = collect_shows(reg)
    ent = ents.load(entities_file)
    ent.lenses = {key: value for key, value in ent.lenses.items() if key == "signals"}
    cos = build_companies(reg, annotate(reg, ent))
    iruns = [r["influencer"] for r in runs if r["influencer"]["scored"]]  # influencer episodes: their own registry, in no ranking, show, company or count
    enrich(iruns)
    ireg = {k: v for k, v in build_episodes(iruns).items() if isinstance(v["score"], int) and k not in reg
            and style.get(norm_show(v.get("show"))) != "interview"}  # a show moved back to interviews leaves Social the same way
    if unscored := [e["title"][:60] for k, e in moved.items() if k not in ireg]:
        print(f"[site] warning: {len(unscored)} episodes of shows now marked Social have no Social score and are listed nowhere: "
              + "; ".join(unscored[:5]))
    if nolink := [e["title"][:60] for e in ireg.values() if not e.get("youtube_url")]:  # Social is the YouTube side: every video links to YouTube
        print(f"[site] warning: {len(nolink)} Social episodes have no YouTube link (run `sigma links --ytsearch` on a Mac, or `sigma show-links --ytsearch`): "
              + "; ".join(nolink[:5]))
    for e in ireg.values():
        e.update(influencer=True, topics=[], edges={}, lenses=[], people=[], _marks=social_mark(), _show_path="")
    ipub = collect_tickers([{"claims": [c for c in r["claims"] if c.get("episode_id") in ireg]} for r in iruns])[0]
    allreg = {**reg, **ireg}
    try:
        source_of = creators.source_names(SOURCES_FILE)
    except OSError:
        source_of = {}
    crs = creators.load(CREATORS_FILE)
    show_owner = {norm_show(n): c.id for c in crs for s in c.sources for n in source_of.get(s, [])}
    views = x_views(published)
    cpages = {}  # creator id -> (creator, videos, posts): a creator with nothing to list has no page
    for c in crs:
        eps_, posts_ = creator_items(c, ireg, views, show_owner)
        if eps_ or posts_:
            cpages[c.id] = (c, eps_, posts_)
    handle_page = {h.lower(): creator_path(cid) for cid, (c, _, _) in cpages.items() for h in c.x}
    for e in ireg.values():  # a Social row's show name links the creator's page
        if (cid := show_owner.get(norm_show(e.get("show")))) in cpages:
            e["_show_path"] = creator_path(cid)
    for e in reg.values():
        e["_show_path"] = show_path(e["show"]) if e["show"] in shows else ""
    for r in runs:  # issue pages and claim lists link the show the episode registry settled on
        for x in r["episodes"] + r["claims"]:
            x["_show_path"] = (reg.get(x.get("episode_id") or x.get("id")) or {}).get("_show_path", "")
    newest = runs[0]["date"] if runs else ""
    DAILY_RUNS = {r["name"] for r in runs if r["kind"] == "daily"}
    SITE_YEAR = int(newest[:4]) if newest[:4].isdigit() else 0
    sm: list[tuple] = []
    adays = signals_site.load(published)[0]  # Signals data adds the Signals panel to the home page and the Signals view to /x/
    signals = bool(adays)

    def emit(path: str, html_s: str, md_s: str, last: str = "") -> None:
        """Write an HTML page and its Markdown twin, and list both in the sitemap."""
        write(out / file_of(path), html_s)
        write(out / file_of(md_of(path)), md_s)
        sm.extend([(path, last or newest), (md_of(path), last or newest)])

    write(out / "style.css", TOKENS.read_text(encoding="utf-8") + CSS.replace("__MARK__", "/logo.svg") + BOARD_CSS + (signals_site.CSS if signals else ""))
    if ASSETS.is_dir():
        for f in ASSETS.iterdir():
            shutil.copy(f, out / f.name)
    eds = load_editions(published)
    emit("/", index_page(runs, reg, ent, side=signals_site.panel(adays), ireg=ireg), index_md(runs, reg, pub, people, ireg, eds, adays))
    signals_site.build(published, out, emit, sm, newest)
    research_html, research_markdown = research_index_page(research_posts)
    emit("/research/", research_html, research_markdown, research_posts[0]["date"] if research_posts else newest)
    research_post_pages(research_posts, emit, out, sm)
    sm.append(("/research/index.json", research_posts[0]["date"] if research_posts else newest))
    write(out / file_of("/alpha/"), redirect_page("/signals/", "Signals", md_of("/alpha/")))
    write(out / file_of(md_of("/alpha/")), doc(["# Signals", "", f"Moved to [Signals]({absu('/signals.md')})."]))
    if signals:
        write(out / file_of("/podcasts/"), redirect_page("/", PODCASTS_NAME, "/index.md"))
        write(out / "podcasts.md", doc([f"# {PODCASTS_NAME}", "", f"Moved to [the home page]({absu('/index.md')})."]))
    emit("/themes/", themes_page(runs), themes_index_md(runs, reg))
    emit("/shows/", shows_index(shows, ent), shows_md(shows, ent))
    emit(TAGS_PATH, tags_page(pub, people, cos, ent), tags_md(pub, people, cos))
    for old, k in (("/companies/", "companies"), ("/people/", "people")):  # the two indexes live on the Tags page now; their Markdown lists stay for agents
        write(out / file_of(old), redirect_page(f"{TAGS_PATH}#{k}", k.capitalize(), md_of(old)))
    write(out / file_of(md_of("/companies/")), companies_md(cos))
    sm.append((md_of("/companies/"), newest))
    emit(NOTICE_PATH, notice_page(), notice_md())
    emit("/find/", find_page(ent, newest_of(*(e["date"] for e in allreg.values()))), find_md(ent))
    write(out / file_of(SOCIAL_PATH), redirect_page("/", FEED_NAME, md_of(SOCIAL_PATH)))
    write(out / file_of(md_of(SOCIAL_PATH)), doc([f"# {FEED_NAME}", "", "Moved to [the home page](/index.md)."]))
    for e in eds:
        annotate_posts(e["posts"] + e["more"], ent, cos, pub)
        for p in e["posts"] + e["more"]:
            p["_creator_path"] = handle_page.get(str(p["handle"]).lower(), "")
        lh, lm = signals_site.lead(adays, e["date"])
        emit(x_day_path(e["date"]), edition_page(e, ent, "day", lh), edition_md(e, ent, lm), e["date"])
    if not eds:
        emit("/x/", page(f"X · {SITE}", "<h1>X</h1><p>No editions are published yet.</p>", "social", md="/x.md"), doc(["# X", "", "No editions are published yet."]), newest)
    if eds:
        week = [e for e in eds if e["date"] >= (date.fromisoformat(eds[0]["date"]) - timedelta(days=6)).isoformat()]
        lh, lm = signals_site.lead(adays, eds[0]["date"])
        emit("/x/", edition_page(eds[0], ent, "today", lh), edition_md(eds[0], ent, lm), eds[0]["date"])
        emit("/x/week/", week_page(week, ent), week_md(week), eds[0]["date"])
        emit("/x/archive/", archive_page(eds), archive_md(eds), eds[0]["date"])
    bh, bm = board_pages(published, reg, ireg, {norm_ticker(t): t for t in (*ipub, *pub)})
    emit(SENTIMENT_PATH, bh, bm)
    for old in OLD_BOARD_PATHS:  # not in the sitemap: they only point on
        write(out / file_of(old), redirect_page(SENTIMENT_PATH, SENTIMENT_NAME, md_of(old)))
        write(out / file_of(md_of(old)), doc([f"# {SENTIMENT_NAME}", "", f"Moved to [{SENTIMENT_NAME}]({absu(md_of(SENTIMENT_PATH))})."]))
    write(out / "find-index.json", json.dumps(find_index(allreg, ent, cos), ensure_ascii=False, separators=(",", ":")) + "\n")
    write(out / file_of(md_of("/people/")), people_md(people))
    sm.append((md_of("/people/"), newest))
    index = []
    home_rows = feed_rows(reg, ireg)
    home_days = {e["date"][:10] for e in home_rows}
    for r in runs:
        p = run_path(r["name"])
        if to := run_redirect(r, home_days):  # the address lands on that day in the home page's Newest list; the Markdown twin and claims stay
            write(out / file_of(p), redirect_page(to, issue_title(r), run_md_path(r["name"])))
            write(out / file_of(md_of(p)), run_md(r, reg))
            sm.append((md_of(p), r["date"]))
        else:
            emit(p, run_page(r), run_md(r, reg), r["date"])
        if r["claims"]:
            write(out / "runs" / r["name"] / "claims.jsonl", jsonl(r["claims"]))
        row = {"run": r["name"], "kind": r["kind"], "date": r["date"], "episodes": len(r["episodes"]),
               "claims": len(r["claims"]), "page": f"/runs/{r['name']}/", "claims_path": f"/runs/{r['name']}/claims.jsonl"}
        if r.get("themes"):
            write(out / "runs" / r["name"] / "themes.json", dump(r["themes"]))
            row["themes_path"] = f"/runs/{r['name']}/themes.json"
        index.append(row)
    all_claims = [c for r in runs for c in r["claims"]]
    write(out / "claims.jsonl", jsonl(all_claims))
    write(out / "runs.json", json.dumps({"runs": index, "claims_path": "/claims.jsonl"}, indent=1, ensure_ascii=False) + "\n")
    tj = []
    for sym, cl in sorted(pub.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        p = ticker_path(sym)
        last = max(claim_date(c) for c in cl)
        emit(p, ticker_page(sym, cl, ipub.get(sym, [])), ticker_md(sym, cl, allreg, ipub.get(sym, [])), last)
        tj.append({"symbol": sym, "claims": len(cl), "episodes": len({c.get("episode_id") for c in cl}), "latest_date": last,
                   "page": absu(p), "md": absu(md_of(p))})
    for sym, cl in sorted(ipub.items()):  # a ticker only influencers named still gets the page their chips link to; the ticker index leaves it out
        if sym not in pub:
            emit(ticker_path(sym), ticker_page(sym, [], cl), ticker_md(sym, [], allreg, cl), max(claim_date(c) for c in cl))
    pj = []
    for p_ in sorted(people.values(), key=lambda p: (-len(p["claims"]), p["name"])):
        p = person_path(p_["slug"])
        last = max(claim_date(c) for c in p_["claims"])
        emit(p, person_page(p_, ents.affiliation(ent, p_["slug"]), cos), person_md(p_, reg), last)
        pj.append({"slug": p_["slug"], "name": p_["name"], "roles": roles_of(p_), "claims": len(p_["claims"]),
                   "episodes": len({c.get("episode_id") for c in p_["claims"]}), "latest_date": last,
                   "page": absu(p), "md": absu(md_of(p))})
    have = {norm_ticker(t): t for t in (*ipub, *pub)}  # every ticker that has a page
    for cid, (c, eps_, posts_) in cpages.items():
        emit(creator_path(cid), creator_page(c, eps_, posts_, have), creator_md(c, eps_, posts_),
             newest_of(*(e["date"] for e in eps_), *(p["date"] for p in posts_)))
    for name, eps in shows.items():
        emit(show_path(name), show_page(name, eps, ent), show_md(name, eps, reg, ent), eps[0]["date"])
    cj = []
    for c in sorted(cos.values(), key=lambda c: (-len(c["episodes"]), c["name"].lower())):
        p = company_path(c["id"])
        emit(p, company_page(c, ent, pub), company_md(c, reg, ent), c["episodes"][0][0]["date"])
        cj.append({"id": c["id"], "name": c["name"], "kind": c["kind"], "ticker": c.get("ticker"), "lenses": c["lenses"],
                   "episodes": len(c["episodes"]), "claims": len(c["claims"]), "latest_date": c["episodes"][0][0]["date"],
                   "page": absu(p), "md": absu(md_of(p))})
    for e in sorted(reg.values(), key=lambda e: (e["date"], e["id"]), reverse=True):
        if e["page"]:
            emit(e["page"], episode_page(e, ent, cos), episode_md(e), e["date"])
    for e in sorted(ireg.values(), key=lambda e: (e["date"], e["id"]), reverse=True):
        if e["page"]:
            emit(e["page"], episode_page(e, ent, cos), episode_md(e), e["date"])
    for e in home_rows:  # the summaries a home-page row opens to (top_entry expand)
        if e["page"] and e["claims"]:
            write(out / file_of(claims_path(e["id"])), claims_fragment(e))
    write(out / "episodes.md", episodes_md(reg))
    sm.append(("/episodes.md", newest))
    ej = [episode_json(e) for e in sorted(reg.values(), key=lambda e: (e["date"], e["id"]), reverse=True)]
    write(out / "tickers.json", dump({"base_url": BASE_URL, "tickers": tj}))
    write(out / "people.json", dump({"base_url": BASE_URL, "people": pj}))
    write(out / "episodes.json", dump({"base_url": BASE_URL, "episodes": ej}))
    write(out / "shows.json", dump({"base_url": BASE_URL, "shows": shows_json(reg, ent)}))
    write(out / "companies.json", dump({"base_url": BASE_URL, "companies": cj}))
    write(out / "llms.txt", llms_txt(runs, reg, pub, people, ireg, eds, adays or None))
    write(out / "llms-full.txt", llms_full(runs, reg))
    write(out / "robots.txt", robots_txt())
    sm += [("/llms.txt", newest), ("/llms-full.txt", newest)]
    write(out / "sitemap.xml", sitemap_xml(sm))
    return {"runs": len(runs), "tickers": len(pub), "claims": len(all_claims), "people": len(people), "episodes": len(reg),
            "social": len(ireg)}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="sigma site", description="build the static website from published/")
    ap.add_argument("--out", default="dist")
    ap.add_argument("--published", default=str(data_root() / "published"))
    ap.add_argument("--base-url", default=os.environ.get("SIGMA_BASE_URL") or None,
                    help=f"public origin used in absolute URLs (env SIGMA_BASE_URL; default {BASE_URL})")
    args = ap.parse_args(argv)
    s = build(Path(args.published), Path(args.out), args.base_url)
    print(f"[site] built {s['runs']} runs, {s['tickers']} tickers, {s['people']} people, {s['episodes']} episodes, "
          f"{s['claims']} claims into {args.out}")


if __name__ == "__main__":
    main()
