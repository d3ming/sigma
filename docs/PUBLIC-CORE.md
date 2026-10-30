# Public code and private inputs

The public repository owns the tools, checks, prompts, schemas and site. The operator owns their sources, editorial decisions and content.

The boundary is a configured data root. A clone starts with the example set and needs no private repository. Local reference copies and deletion notes belong in ignored `.local/`; scratch work belongs outside the checkout.

Published output is an artifact, not source code. The build reads allowed content from the data root and creates the public site locally. Deployment uploads that checked build, rather than asking a remote builder to find private content in Git.

An input can be evidence without being publishable. Full transcripts, follow reasons, drafts, account text and the private call ledger stay outside the public package. Research content passes an explicit allowlist and a private-text check before the builder replaces its output.

Removing a file from Git does not retract it from public history. Scan the exact proposed tree and its reachable history before pushing; never use branch deletion as a privacy control.
