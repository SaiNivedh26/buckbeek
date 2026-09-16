# Existing pipeline function updates

These directories replace the source of the existing `build-submit-control` and
`build-submit-analyzer` resources. Update the `source_dir` values in the original build-submit
Terraform state to these paths (or copy these files over its current function sources). Do not
declare second Cloud Functions with the same names.

Set `GITCRAWL_AGENT_URL` on the analyzer function to the private Cloud Run service URL. Its existing
service account needs `roles/run.invoker`, which is granted by `infra/main.tf` through
`invoker_member`.

The original pipeline Terraform state also owns the Cloud Tasks cleanup queue and caller identity.
Both functions enqueue authenticated, idempotent deletion of `submissions/<id>/`; agent artifacts
under `agents/` are never included in cleanup.
