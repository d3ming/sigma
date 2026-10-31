# Architecture

An agent makes editorial judgments. Deterministic code collects sources, transcribes, validates the agent's files, stores evidence and builds the site. There are no model calls in the pipeline: prompts and schemas make each handoff inspectable.

The data root is the only owner of deployment-specific inputs and output. Code resources stay with the package; private follows, runs, caches, transcripts and publication records stay with the operator. This prevents a clone from silently reading another checkout's state.

Published claims remain tied to their source and timestamp. A schema failure, copied passage or ungrounded number stops the publication step. Scores and stance labels are retained so yesterday's editorial judgment does not shift when a prompt changes. Manifest writes are locked because transcription and editorial work may overlap.

The static site reads checked publication records. Research posts pass a separate opt-in check before any build output is replaced. The private library retains transcript text for local research; transcripts are not published.

Deployment builds on the operator's machine, then uploads the prebuilt output. Content determines whether a deployment is needed; a Git commit is insufficient because the private data root can change independently. The same frozen content must pass checks and reach the upload.

The initial review is `seed` into `develop`. Reviewing source and cutting over a production instance are separate decisions. Publishing a new page type, changing a domain, or changing an account needs the owner's explicit authorization.

Explicit transcript speaker labels are checked at the cited segment. Unlabelled transcripts, including ordinary Whisper output, still need editorial attribution review; Sigma does not infer diarization.

## Episode editing

Investment scores and their claims remain owned by ranking. A run may separately contain `editor.json`, written with
`prompts/edit.md` and checked by `python -m sigma.editor <run>`. Each edit names an existing episode and the SHA-256
of its complete timestamped source transcript. `key_insights` is importance ordered and has no ticker requirement;
`dense_summary` is chronological. The publication exporter validates source identity, intervals, explicit speaker
labels, figures in each cited interval and extended copied text before replacing output. Editorial inference remains
separate from the attributed account; automated checks do not establish semantic truth or identify unlabelled voices.

The exporter projects the two fields into episode metadata without rewriting scores, claims or stance labels. Frozen
publication inputs retain the editorial file and its transcript evidence. [Editor evaluation](editor-evaluation.md)
defines the separate, source-based prompt refinement and model comparison workflow. The app JSON and episode Markdown keep both
fields. Expanding a homepage card shows key insights; the episode page additionally shows the dense summary. Episodes
without an edit retain their existing claim view. Publisher artwork is metadata; a verified YouTube identity can supply
a video thumbnail. Neither image selection nor editorial editing invents a clip or changes the source timeline.
