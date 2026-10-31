# Refine the editor with saved source evidence

Keep editorial prompt experiments separate from publishing. Compare edits against fixed complete transcripts,
retain the evidence for each video, and promote a prompt only when the writing meets the declared target without
losing readability, fidelity or useful substance. Investment scores, ranked claims and stance labels remain unchanged.

The editor follows [the editing prompt](../prompts/edit.md); the output contract belongs to
[the editor schema](../schema/editor.schema.json). The reviewer follows
[the evaluation prompt](../prompts/evaluate-edit.md), rubric `episode-edit-v1`. This procedure does not add a model
API, change the configured editor model or automatically deploy a winning candidate.
The [experimental editing prompt](../prompts/edit-experimental.md) is a candidate for this procedure, not the default.
Keep its evaluated version separate until it meets the promotion rules below.

## Freeze the comparison before generating edits

Choose a small development set spanning interview, panel or creator formats, and a separate held-out set. Record
the split before any trial. Have a source reader map the complete conversation into substantive topics and source
intervals before seeing candidate edits. Keep non-company insights, disagreements, late topics, real qualifications
and ad boundaries in that reference. Editors receive the source and editing contract; reviewers also receive the
frozen topic reference. Neither receives the blind-label mapping.

Keep the evaluation under the configured private data root, with one directory per experiment and episode:
Full transcripts and any requests or logs containing their raw text stay local and Git-ignored, including in a
private operator repository. Back them up separately. Version hashes, source references and editorial results.

```text
evaluations/editor/<experiment>/
  protocol.json                 # split, targets, round limit, seed, frozen rubric and model settings
  evaluator.md                 # exact evaluator prompt used
  sources/<episode>/
    source.json                # ID, original URL, transcript hash and clock, source-file reference
    transcript.md              # immutable complete transcript snapshot
    topics.json                # versioned source-based reference with intervals
  rounds/<round>/
    editor.md                  # exact editor prompt used
    trials/<episode>/<trial>/
      request.json             # complete instructions, model/runtime, effort and generation settings
      raw-editor.json          # untouched generated output, including failed attempts
      validation.json          # command, exit status and output
      usage.json               # available token counts, elapsed time and measurement limits
    blind-map.json             # seeded shuffle; kept from editors and reviewers
    reviews/<episode>.json     # raw evaluator response and reviewer provenance
    decision.md                # per-case gates, scores, choice, changes and remaining uncertainty
  result.md                    # retained prompt, all rounds, held-out outcome and limits
```

Hash the transcript, prompts, reference, candidate and review files in the experiment record. Record the source
revision and actual model identifier, effort, runtime and judge settings. Missing usage remains missing; do not
turn subscription usage into invented API charges. Keep repairs as new attempts with their own validation results.
Never overwrite a failed raw draft or quietly substitute a manually corrected candidate.

## Run at most three refinement rounds

1. Generate a retained-prompt baseline and a proposed-prompt edit on identical development sources and editor
   settings. Use fresh editor contexts. Change one coherent instruction problem per round; do not rescore episodes
   or change their selection. Preserve both fields required by the schema, including for creator videos.
2. Validate each candidate in an isolated scratch run containing its exact transcript and manifest, using
   `python -m sigma.editor <scratch-run>`. Save command output and failure status. Never replace a real run's edit
   to conduct an experiment. Automated checks cover schema, fingerprints and certain grounding errors; review
   attribution, semantic claims, ad boundaries and coverage against the full source too.
3. Make derived review copies with prompt versions and other model or trial identifiers removed; preserve the raw
   originals and record the copy-to-original hash mapping. Remove revealing paths from review copies of validation
   logs too. Shuffle anonymous labels using the recorded seed. Give a fresh reviewer the frozen evaluator prompt,
   source, topic reference, anonymous copies and validation evidence. Save its exact request and raw result. Recompute score
   totals and qualification gates outside the reviewer. Do not expose candidate model names, prompt versions,
   prior scores or the desired winner. The coordinator independently checks material findings and representative
   source passages; record whether a human reviewed any output.
4. Qualify only when every evaluated case has all hard gates passed, no unresolved material error, total at least
   85/100 and readability at least 8/10. Readability, fidelity and coverage must each be at least the retained baseline's values
   on that case. A mean score cannot conceal a failed episode. Prefer source-anchored pairwise judgments when
   numeric differences are small. A tie keeps the retained prompt.
5. If a candidate fails, fix the highest-impact evidenced instruction problem and run another fresh round. Freeze
   the evaluator and references throughout; never tune the rubric to make a candidate pass. Stop after three
   candidate rounds, a qualifying candidate, or a source/reference error that invalidates the comparison. At the
   limit, keep the retained prompt and record unresolved defects. A validation repair counts as another attempt,
   not evidence that the original output passed.

After development qualifies, run the chosen prompt and retained baseline once on untouched held-out cases under
the same gates. Include a commercial-read or uncertain-attribution edge case and a near miss: useful discussion
of advertising must survive despite the instruction to remove ads. Do not tune against those results. A held-out
failure blocks promotion; if that episode is used for refinement later, relabel it development and reserve new
held-out evidence. Cases already used to improve the prompt are development evidence, however unfamiliar they
look to a new reviewer.

The target and round limit are operational stop rules, not a claim that an 85 is objectively good. Keep raw
findings beside scores. If the target is met, promote only the tested prompt and make any content publication a
separate reviewed release. Material source-reference corrections start a newly versioned comparison.

## Compare writing models without changing the test

First freeze the chosen editor prompt and evaluator. Give each model the same complete transcripts, task, schema
and supported generation settings. Interleave model runs and repeat at least two independent samples per model
per episode; retain failed attempts in the outcome and cost counts. Randomize review order, include a swapped-order
comparison to detect position effects, and record the evaluator model separately. Compare per-episode hard-failure
rates, blind preferences, score ranges, coverage, output length, latency and measured tokens. Separate generation
from review and repair costs. Prices, if used, need dated provider terms and the actual billing route.

A small pilot proves that the evaluation process can run. It does not establish a general writing-model winner.
Use a second independent judge or human source review to check close calls and any apparent model-family
advantage. If a runtime cannot expose tokens or settings, label those comparisons unmeasured rather than estimate
them from words. Keep the same held-out discipline when testing models; inspecting a result consumes that test
case for further tuning.
