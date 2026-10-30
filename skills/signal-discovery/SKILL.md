---
name: signal-discovery
description: Find fresh, evidence-backed leads relevant to US-listed stocks across primary disclosures, news, podcasts, X and public communities. Use for a bounded ticker, sector or market sweep; use source-reading for a supplied source.
---

# Discover US stock-market signals

Find developments that could change a reader's understanding of a US-listed business or its operating environment. A lead is a question supported by evidence, not a trade recommendation or a claim of proven excess returns.

Use the requested universe and time window. If unspecified, start with recent developments relevant to the requested company or sector. Do not silently impose a 30-day horizon: an earnings event and a structural change need different windows.

Choose sources for the question. Start with issuer releases, investor relations, filings and regulator or economic releases where available. Use podcasts, YouTube and X to find operator observations and public claims. News, specialist sites, Reddit, Hacker News and GitHub can reveal leads; follow their claims back to an original document, author or event. Engagement indicates attention, not business materiality or independent confirmation.

Use the source tools actually available in this environment. Inspect `sigma --help` for the podcast and X paths. Separate a source that returned no results from one that could not be searched; do not claim complete coverage when a connector, account or date range was unavailable. Do not install tools, acquire keys or change permissions merely to finish a sweep.

Hand the promising sources to [source-reading](../source-reading/SKILL.md). Keep a lead only when you can state:

- The source URL, author or publisher, publication time when supplied, and what changed.
- The US-listed issuer or market exposure, supported by evidence; a sector relationship is not automatically a ticker match.
- The causal path to revenue, costs, supply, demand, capital spending or the market environment.
- The catalyst and timing if known, what is new relative to prior reports, and the strongest contrary evidence or unresolved question.

Merge repeated coverage of one underlying event. Ten reposts are one source of evidence. Prefer a few material leads to a padded list; say when no supported lead cleared the bar.

Save the bounded sweep, source coverage and rejected leads with reasons in the configured data root's private notes, never in the code repository. These are discovery notes, not checked publication records. Do not feed article claims into transcript-only validators, invent missing timestamps, or bypass the publication gate.
