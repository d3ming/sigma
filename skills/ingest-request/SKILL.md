---
name: ingest-request
description: Run a one-off request to ingest named sources (episodes, videos, X posts, articles, PDFs, filings) and turn them into grounded notes and, when asked, a report or post. Use for "ingest A, B and C, then report on D"; not for the scheduled daily or weekly editions.
---

# Ingest on request

A request names sources and, usually, a topic. Do what it asks, well: read every named source in full, keep every claim tied to
its source, and write only what the sources support. Do not widen it into a sweep; suggest extra sources in the reply instead.

## 1. Record the request

Write `$SIGMA_DATA_ROOT/requests/<YYYY-MM-DD>-<slug>.md` before ingesting: who asked, the sources as given, the topic, the
output wanted (notes only, a private report, or a public post), the deadline if any, and the model and transcription
budget the job will use. Add one line per source as it lands
(ingested, partial, or unreadable and why). This file is how the requester follows the job.

## 2. Ingest each source by type

| Source | How | State |
|---|---|---|
| Podcast episode or YouTube video | `sigma custom-run <slug> --url <url>`, then the transcribe and status commands it prints | Checked; claims cite seconds |
| X post or thread | The reader `x.reader` in `$SIGMA_DATA_ROOT/operator.json` names ([rules](../../docs/operators.md#x-reader)), read-only. Absent, null or `bird`: [Bird](https://github.com/steipete/bird) signed in through the operator's browser; run `bird thread <id> --all --json` and keep the tweets whose `authorId` is the root's. `official`: the official X tools; fetch the post with full text and articles, then page the conversation and keep the root author's tweets. Either way that is the whole multi-tweet thread plus the author's own replies, which often hold the links the post leaves out | Fails when the reader cannot read the post (expired session, rate limit you cannot wait out); then recover below or record it unreadable |
| Article, PDF, filing, release | [source-reading](../source-reading/SKILL.md): read the original, keep the canonical URL and a section or paragraph locator | Private notes only; no publish check yet |

An episode the owner sends gets this full run even when a weekly run already holds it: `custom-run` reuses that
transcript, so nothing is transcribed twice. Run `rank-prep --rescore` on the new run: without it the weekly run's stored
score is reused.

When an X read fails, look for a public copy instead of working around the login: search the post's numeric ID in
quotes, then the handle with a distinctive phrase, and prefer a copy the author controls. A mirror or archive is a
third-party copy: match the handle, ID and date, check for a missing ending or thread gaps, and record the copy's URL
and that it is not the original. If nothing reliable turns up, ask the requester for the text or screenshots.

Prefer the original over a summary of it: the issuer's filing over coverage of it, the episode over a clip. A paywalled or
login-only source is read only through access the owner already has; otherwise record it as unreadable.

## 3. Grounded notes

Follow [source-reading](../source-reading/SKILL.md) for each source: speaker or author, publication time, retrieval time,
URL, locator, what the source says, what corroborates it, and your inference, kept apart. Save them in the data root's
private notes beside the request; a contributor delivers them by data pull request ([operators](../../docs/operators.md)).

## 4. Report or post

Write from the notes only. Every sourced sentence names its speaker and links its locator; an opinion is labelled as one.
Do not restate the owner's private research or the other teams' work; link to the request's notes for the requester instead.

- A **private report** goes where the request says, outside this repository.
- A **public post** is a draft until the owner has curated it (AGENTS.md, what needs the owner's go): it joins the data
  root's `research/index.json` only after his explicit yes to that draft. Podcast and X claims
  pass their existing checks; a claim from an article, PDF or filing has no publish check yet, so it stays out of public
  output.

Finish by updating the request file and replying with what was ingested, what could not be read and why, and where the
output is. Record in the request file the hours from request to output and whether every citation check passed; add
whether the requester reused the notes when you learn it.
