"""Research article bodies: a small, closed markup rendered to escaped HTML.

Paragraphs are separated by blank lines. Block forms: `## heading`, `- ` list items, `> ` quote lines whose last line
starts with `— ` (the attribution), `| a | b |` tables (first row is the header), `::video <youtube id> <start seconds>
<caption>`, a `::: timeline` block closed by `:::` with one `date | text` row per line. Inline: `[text](https://…)`
links and `**bold**`. Anything else is text and is escaped.
"""
from __future__ import annotations

import html
import re

LINK = re.compile(r"\[([^\]]+)\]\((https://[^\s)]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*")
VIDEO = re.compile(r"::video ([A-Za-z0-9_-]{11}) (\d+) (.+)\Z")
SPLIT = re.compile(r"\s*\|\s*")


def esc(v) -> str:
    return html.escape(str(v), quote=True)


def inline(text: str) -> str:
    out, last = [], 0
    for m in LINK.finditer(text):
        out.append(BOLD.sub(r"<b>\1</b>", esc(text[last:m.start()])))
        ext = "" if m.group(2).startswith("https://sigma.") else ' rel="noopener noreferrer"'
        label = BOLD.sub(r"<b>\1</b>", esc(m.group(1)))
        out.append(f'<a href="{esc(m.group(2))}"{ext}>{label}</a>')
        last = m.end()
    out.append(BOLD.sub(r"<b>\1</b>", esc(text[last:])))
    return "".join(out)


def cells(line: str) -> list[str]:
    return SPLIT.split(line.strip().strip("|").strip())


def video(vid: str, start: int, caption: str) -> str:
    thumb = f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg"
    watch = f"https://www.youtube.com/watch?v={vid}&t={start}s"
    return (f'<figure class="yt-embed"><a class="yt-lite" href="{esc(watch)}" data-id="{vid}" data-start="{start}" rel="noopener noreferrer"'
            f' style="background-image:url({esc(thumb)})"><span class="yt-play" aria-hidden="true"></span>'
            f'<span class="sr">Play video: {esc(caption)}</span></a><figcaption>{inline(caption)}</figcaption></figure>')


def block(lines: list[str]) -> str:
    first = lines[0]
    if first.startswith("## "):
        return f'<h2 class="ah">{inline(first[3:])}</h2>'
    if VIDEO.match(first):
        vid, start, caption = VIDEO.match(first).groups()
        return video(vid, int(start), caption)
    if first.startswith("::: "):
        kind, rows = first[4:].strip(), [cells(l) for l in lines[1:] if l.strip() != ":::"]
        if kind == "timeline":
            items = "".join(f'<li><span class="tl-d">{inline(r[0])}</span><div>{inline(" | ".join(r[1:]))}</div></li>' for r in rows)
            return f'<ol class="timeline">{items}</ol>'
        raise ValueError(f"unknown article block ::: {kind}")
    if first.startswith("> "):
        body = [l[2:] for l in lines if l.startswith("> ")]
        who = body.pop() if body and body[-1].startswith("— ") else ""
        cap = f'<figcaption>{inline(who)}</figcaption>' if who else ""
        return f'<figure class="pull"><blockquote>{inline(" ".join(body))}</blockquote>{cap}</figure>'
    if first.startswith("|"):
        head, *rest = [cells(l) for l in lines if not re.fullmatch(r"\|[\s:|-]+\|?", l.strip())]
        th = "".join(f"<th>{inline(c)}</th>" for c in head)
        tr = "".join("<tr>" + "".join(f'<td data-label="{esc(h)}">{inline(c)}</td>' for h, c in zip(head, r)) + "</tr>" for r in rest)
        return f'<div class="tw"><table class="grid"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'
    if first.startswith("- "):
        return "<ul class=\"al\">" + "".join(f"<li>{inline(l[2:])}</li>" for l in lines if l.startswith("- ")) + "</ul>"
    return f"<p>{inline(' '.join(l.strip() for l in lines))}</p>"


def kind(line: str) -> str:
    for prefix, k in (("## ", "h"), ("::video", "v"), ("- ", "li"), ("> ", "q"), ("|", "t")):
        if line.startswith(prefix):
            return k
    return "p"


def render(body: str) -> str:
    blocks, cur, fence = [], [], False
    for line in body.strip().splitlines():
        if line.startswith("::: "):
            if cur:
                blocks.append(cur); cur = []
            fence = True
        if fence:
            cur.append(line)
            if line.strip() == ":::":
                blocks.append(cur); cur, fence = [], False
            continue
        if not line.strip():
            if cur:
                blocks.append(cur); cur = []
            continue
        if line.startswith("::video") and not VIDEO.match(line):
            raise ValueError(f"malformed article video line: {line[:60]}")
        k = kind(line)
        if cur and (k != kind(cur[0]) or k in ("h", "v")):
            blocks.append(cur); cur = []
        cur.append(line)
    if fence:
        raise ValueError("article ::: block is never closed")
    if cur:
        blocks.append(cur)
    html_out = "".join(block(b) for b in blocks)
    return f'<div class="article">{html_out}</div>' + (VIDEO_JS if "yt-lite" in html_out else "")


VIDEO_JS = """<script>document.querySelectorAll('.yt-lite').forEach(a=>a.addEventListener('click',e=>{e.preventDefault();const f=document.createElement('iframe');
f.src='https://www.youtube-nocookie.com/embed/'+a.dataset.id+'?autoplay=1&start='+a.dataset.start;f.title=a.textContent;f.allow='autoplay; encrypted-media; picture-in-picture';f.allowFullscreen=true;
a.replaceWith(f)}))</script>"""

CSS = """
.archive.articles li{grid-template-columns:1fr;gap:var(--space-1);padding:var(--space-5) 0}
.archive.articles a{font:600 var(--text-heading)/1.3 var(--font-sans);letter-spacing:-.015em;text-wrap:balance}
.archive.articles .lede{font-size:var(--text-section);margin:0}
.article{font-size:1.06rem;line-height:1.7}
.article>p{max-width:68ch}
.article a{text-decoration-color:var(--accent);text-decoration-thickness:1px}
.article h2.ah{display:block;font:600 var(--text-heading)/1.3 var(--font-sans);letter-spacing:-.015em;text-transform:none;color:var(--text);margin:2.4em 0 .5em;padding-top:var(--space-4);border-top:var(--line-1) solid var(--border)}
.article h2.ah::before,.article h2.ah::after{display:none}
.article ul.al{padding-left:1.1em;margin:.6em 0}.article ul.al li{margin:.35em 0;max-width:66ch}
.pull{margin:1.6em 0;padding:0 0 0 var(--space-5);border-left:var(--line-2) solid var(--accent)}
.pull blockquote{margin:0;font:500 1.32rem/1.4 var(--font-sans);letter-spacing:-.01em;color:var(--text);text-wrap:balance}
.pull blockquote::before{content:"\\201C"}.pull blockquote::after{content:"\\201D"}
.pull figcaption{margin-top:var(--space-2);font:400 var(--text-detail) var(--font-mono);color:var(--text-muted)}
.yt-embed{margin:1.6em 0}
.yt-lite,.yt-embed iframe{position:relative;display:block;width:100%;aspect-ratio:16/9;border:0;border-radius:var(--radius-lg);background:#000 center/cover no-repeat}
.yt-play{position:absolute;inset:0;margin:auto;width:68px;height:48px;border-radius:12px;background:var(--yt);opacity:.92}
.yt-play::after{content:"";position:absolute;left:28px;top:14px;border-style:solid;border-width:10px 0 10px 17px;border-color:transparent transparent transparent #fff}
.yt-lite:hover .yt-play{opacity:1}
.yt-embed figcaption{margin-top:var(--space-2);font:400 var(--text-detail) var(--font-mono);color:var(--text-muted)}
.sr{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}
.tw{overflow-x:auto;margin:1.4em 0}
table.grid{width:100%;border-collapse:collapse;font-size:var(--text-row)}
table.grid th{text-align:left;font:500 var(--text-micro) var(--font-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);padding:var(--space-2) var(--space-3);border-bottom:var(--line-1) solid var(--border-strong)}
table.grid td{padding:var(--space-3);border-bottom:var(--line-1) solid var(--border);vertical-align:top;line-height:1.5}
table.grid td:first-child{white-space:nowrap;font-weight:500}
.timeline{list-style:none;margin:1.4em 0;padding:0 0 0 var(--space-5);border-left:var(--line-1) solid var(--border-strong)}
.timeline li{position:relative;padding:0 0 var(--space-5)}
.timeline li::before{content:"";position:absolute;left:calc(-1 * var(--space-5) - 5px);top:.45em;width:9px;height:9px;border-radius:50%;background:var(--accent)}
.tl-d{display:block;font:500 var(--text-caption) var(--font-mono);letter-spacing:.06em;color:var(--accent)}
@media (max-width:600px){table.grid thead{display:none}table.grid,table.grid tbody,table.grid tr,table.grid td{display:block}table.grid tr{padding:var(--space-3) 0;border-bottom:var(--line-1) solid var(--border)}table.grid td{padding:2px 0;border:0}table.grid td:first-child{font-size:var(--text-section)}table.grid td:not(:first-child)::before{content:attr(data-label);display:block;font:500 var(--text-micro) var(--font-mono);letter-spacing:.08em;text-transform:uppercase;color:var(--text-muted);margin-top:var(--space-2)}}
@media (max-width:480px){.pull blockquote{font-size:1.16rem}.article{font-size:1rem}}
"""
