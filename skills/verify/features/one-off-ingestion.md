# Ingest a requested episode

An operator supplies a YouTube or Apple episode URL. Sigma creates or resumes a custom run and records user-pick provenance.

## Sub-features

- `oneoff-url`: accept a supported episode URL without creating a follow.
- `oneoff-reuse`: reuse canonical episode identity and an existing transcript.
- `oneoff-repeat`: repeating intake adds no duplicate or replacement assessment.

## How to get to it (user POV)

- Run `sigma custom-run NAME --url URL` through the configured runtime.
- Existing candidate-list intake is `sigma custom-run NAME --picks FILE`; this does not itself mean a personal pick.

## Driving it with the Sigma verification driver

Preconditions: launch and doctor passed; the fictional video ID `abcdefghijk` already exists in the scratch run/library.
From the source checkout, use the same isolated data root, never the real operator root:

```sh
SIGMA_EVENTS_DIR="$VERIFY_WORK/data/events" SIGMA_DATA_ROOT="$VERIFY_WORK/data" "$SIGMA_PYTHON" -m sigma.cli custom-run verification-pick \
  --url https://youtu.be/abcdefghijk --runs "$VERIFY_WORK/data/runs" --sources ""
```

Record argv/stdout/stderr/exit and the resulting manifest. Require one canonical `yt:abcdefghijk` row,
`user_pick=true`, `has_transcript=true` and an existing reuse source. Repeat the exact command: require zero added
and still one row. Compare the original run’s source, ranking and edit hashes and its library score before/after.
No source list, schedule or publication directory may change. Save those observations under `evidence/oneoff/`.

## Gotchas

- This command does not transcribe or publish. URL acceptance cannot prove a finished episode page.
- An unknown URL can perform network metadata lookup. This offline recipe relies on an exact known ID;
  do not replace it with a real URL unless source acquisition is part of the authorized task.
- New-source ASR, assessment, editing and release require their existing workflows and separate evidence.
- Apple and candidate-list paths are not exercised by the default YouTube recipe; report them unverified.
