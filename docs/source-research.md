# Source skills for US-market signals

Sigma's goal is to find evidence-backed leads relevant to US-listed stocks. Breadth helps discover a development; careful reading establishes what the source actually supports. Neither social popularity nor a generated trade recommendation establishes alpha.

## What the comparisons contribute

[Last30Days](https://github.com/mvanhorn/last30days-skill) separates discovery from a known-topic research run, combines several source types, and distinguishes source availability from empty results. Its [skill](https://github.com/mvanhorn/last30days-skill/blob/main/skills/last30days/SKILL.md) provides useful phase boundaries between finding, judging and synthesizing. Sigma adopts those boundaries. It does not treat engagement as evidence of stock-price impact or import the project's research engine and backend setup.

[Open Deep Research](https://github.com/langchain-ai/open_deep_research) provides a useful bounded research cycle: divide the question, investigate, assess gaps and compress the evidence before writing. Its [prompts](https://github.com/langchain-ai/open_deep_research/blob/main/src/open_deep_research/prompts.py) are a design reference, not a runtime dependency. Sigma keeps the scope small enough that the next useful question is visible rather than launching an open-ended agent debate.

[TradingAgents](https://github.com/TauricResearch/TradingAgents) separates news, market context and sentiment. Its [news analyst](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/analysts/news_analyst.py) and [bear researcher](https://github.com/TauricResearch/TradingAgents/blob/main/tradingagents/agents/researchers/bear_researcher.py) make the value of an explicit countercase clear. Sigma uses that reading discipline while leaving position sizing, price forecasts and trade proposals outside its public signal workflow.

## The Sigma workflow

[signal-discovery](../skills/signal-discovery/SKILL.md) runs a bounded sweep and hands promising sources to [source-reading](../skills/source-reading/SKILL.md). The reader identifies the source claim, US-market exposure, causal path, catalyst, novelty and contrary evidence. Missing evidence rejects the lead rather than inviting a guessed value.

These skills use the reader and connector capabilities available in their host. The executable pipeline supports podcast and X publication checks. Filing, article and community-source readings can inform private leads, but do not acquire a publish path by being written down. Adding another executable source type requires its own evidence contract and checked handoff.
