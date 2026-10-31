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
Keep the concrete examples and contrasts that explain each topic; a topic heading alone does not preserve them.

Write for a reader who has not heard the episode. Open with the specific claim, actor and mechanism, rather than
announcing that the conversation raises an important question. Explain unfamiliar terms on first use. Keep each
insight focused on one mechanism; separate distinct ideas rather than hiding them in a broad safety or leadership
bullet. Preserve examples and reasoning when tightening sentences; do not trade substantive coverage for brevity.

Make `why_it_matters` add a supported consequence, useful distinction or decision the insight changes. Leave it
empty when it would only restate the paraphrase. Put your own extrapolation in `inference`, not in the speaker's
account or an unlabeled implication. State a material qualification where it changes the claim. Do not end every
item with a generic warning that the interview is not independent proof. Attribution and specific uncertainty
must remain wherever a reader could otherwise mistake a prediction, personal impression or anecdote for fact.
Keep titles as precise as their supporting text; a qualified possibility in the body must not become an observed
event in its title. In an unlabelled multi-speaker transcript, use shared or unnamed attribution unless the text
identifies the speaker of that specific reply through self-identification or an explicit named handoff. A nearby
named question, a familiar viewpoint or biographical fit does not establish later turns. Keep useful substance
without guessing who said it; state an uncertainty once where the reader needs it.

Before returning the edit, check for repetitive openings, repeated caveats and implications that repeat the insight.
Rewrite those passages without removing their evidence, conditions or useful detail.
Check every factual sentence in an item, including `why_it_matters`, against its attached source interval. Evidence
elsewhere in the episode does not support that timestamp. Split the item or adjust its interval to include the actual
evidence; do not attach a later warning or example to an earlier discussion merely because their topics match.

Distinguish predictions from events that had already happened when recorded. Attribute company and founder
accounts rather than treating them as independently proven facts. Use a role or
shared attribution when speaker identity is uncertain. Never invent numbers, implications or a trade instruction.
Exclude sponsor reads, promo codes and commercial breaks while preserving pertinent conflict disclosures and
editorial discussion of advertising economics. Leave the original audio and transcript timeline intact; every
interval uses the transcribed source's clock. Paraphrase throughout; do not copy extended source passages.

Run `python -m sigma.editor <run>` before publishing. Publishing validates the optional edit against its source before replacing output. A changed source requires the
edit to be checked again and its fingerprint updated only after that review. A schema, source, number, attribution
or paraphrase failure is repaired in the editor output; never bypass the publication check.
