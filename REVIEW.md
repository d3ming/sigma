# Review a change

Read the exact proposed head and the code it changes. Review the `develop` → `main` release PR. A passing release PR authorizes publication through `make publish`.

Report real wrong outcomes first, with a tight file and line reference. Rate each bug from 1–10 for frequency and impact. If their product is below 5, record it as an issue rather than changing the code. Keep speculative future cases and style preferences out of the blocking findings.

Check the boundaries that can harm a reader:

- Source grounding: speaker, timestamp, link and figures agree with the evidence; no invented fields or copied long passages.
- Private data: operator follows, drafts, positions, account text, credentials and machine paths stay out of the source and publication package.
- Ownership: code resources and operator data have one owner each; no old-name aliases or private-repository fallbacks.
- Publication: the whole allowed package is checked before it can replace output or upload. A refused research post publishes nothing.
- Correctness: selection floors, once-only labels, Pacific dates, locked manifest writes and deleted-post pruning retain their behavior.
- Verification: exercise the actual command and inspect its output. Offline tests use throwaway roots, never operator data. A deploy claim needs deployment evidence.

A missing value is not a bug when it is shown as missing. Public facts about a company are not private positions. Source grounding checks what someone said; it does not establish that their statement is true.

Name what you checked, what you did not check and what you inferred. Leave the owner with the blocker and the smallest complete repair, not a list of possible refactors.

Review once, fix material findings, then verify those fixes and the release gates. Stop when the frozen head passes
and material findings are fixed or explicitly accepted. Record unrelated cleanup and accepted limits in the private
issue tracker; do not restart a broad review after every fix.
