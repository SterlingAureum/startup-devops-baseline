# AI-Assisted Contribution Policy

This policy applies to new or materially changed code, infrastructure,
workflows, tests and documentation beginning with v0.12.0. It supplements the
normal human review and CI process; it does not replace either.

## Human Accountability

The contributor must understand and review AI-assisted output before it enters
the repository. The reviewer remains responsible for architecture, correctness,
security, operational impact, licensing and the accuracy of every claim.

AI-assisted output must pass the same formatting, unit, contract, negative,
security and runtime gates as manually written output. A generated validator is
not evidence unless its assumptions and failure cases were independently
reviewed.

## Prohibited Inputs

Do not supply the following to an AI service that has not been explicitly
approved for that data:

- credentials, tokens, private keys or secret values;
- Terraform state, saved plans or backend access material;
- AWS account/resource identities or private operator evidence;
- customer, personal, regulated or contractual data; or
- private incident logs and unredacted production output.

Use minimized, redacted fixtures when assistance is necessary. Synthetic data
must not be presented as live evidence.

## Source, License and Similarity Review

For externally informed content, retain enough source context for a reviewer to
verify the design and license boundary. Do not insert unattributed copied code,
documentation or restrictive-license material. Material uncertainty blocks the
change until it is resolved or replaced.

Repository-wide license, similarity, SBOM, provenance and AI-assisted content
assurance is completed in v1.0 RC.2. v0.12 changes still require immediate
human review and normal dependency/security scanning.

## Evidence and Claims

- Record whether AI assistance materially influenced a change in the private
  review notes or pull-request review context used by the maintainer.
- Record the human validation commands and their results.
- Keep raw private prompts, credentials and private evidence out of Git.
- Never use AI-generated text to upgrade offline, historical or synthetic
  evidence into a live claim.
- Production approval, pull-request merge, recovery and break-glass decisions
  remain human actions.

## Documentation Authority

New documentation must identify whether it is current guidance, a contract,
evidence or historical explanation. Current documents are maintained with the
capability they describe. Historical and archive documents are not rewritten
merely to adopt current wording, but current workflows and Runbooks must not
depend on superseded guidance.
