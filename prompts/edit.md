# Edit one complete episode

Read the complete source transcript before writing. The investing lens selected the episode; the edit preserves its
most useful, surprising and interesting ideas, including technical mechanisms, company detail, practical mental
models, organizational choices and human questions. An insight needs no ticker. Do not change investment scores,
ranked claims or stance labels.

Write the run's optional `editor.json` against `schema/editor.schema.json`. Include the exact episode ID and the
SHA-256 of its source transcript. Record `prompt_version` so later backfills can distinguish edits. Keep recording
dates separate from publication dates in `context`.

First map the whole conversation into topic beats. Then write two separate fields:

- `key_insights`: importance ordered, with a useful title, a substantial paraphrase, why it matters, the speaker and
  source interval. Preserve the mechanism, unusual example and qualification that make each idea worth reading.
  Include company names only when relevant. Put an editorial inference in its separate field; never present it as
  the speaker's statement. These render as bullets when a homepage episode expands.
- `dense_summary`: chronological timestamped sections covering the substantive beginning, middle and end. Explain
  the conversation's reasoning and development in connected prose. Preserve concrete examples, disagreements and
  caveats. These render on the episode page, separately from key insights.

Use enough detail to recover the conversation's substance. For an hour-long interview, a starting point is 7–10
insights and 12–18 narrative sections; the evidence decides the length. Avoid padding, repeated explanations and
lists of topics without their substance. Audit the final edit against every substantive source topic.

Distinguish predictions from events that had already happened when recorded. Attribute company and founder
accounts rather than treating them as independently proven facts. Use a role or
shared attribution when speaker identity is uncertain. Never invent numbers, implications or a trade instruction.
Exclude sponsor reads, promo codes and commercial breaks while preserving pertinent conflict disclosures and
editorial discussion of advertising economics. Leave the original audio and transcript timeline intact; every
interval uses the transcribed source's clock. Paraphrase throughout; do not copy extended source passages.

Run `python -m sigma.editor <run>` before publishing. Publishing validates the optional edit against its source before replacing output. A changed source requires the
edit to be checked again and its fingerprint updated only after that review. A schema, source, number, attribution
or paraphrase failure is repaired in the editor output; never bypass the publication check.
