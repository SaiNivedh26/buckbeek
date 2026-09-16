# GitCrawl core infrastructure

This Terraform root owns the authenticated submission pipeline: Cloud Storage, control and
analyzer functions, Eventarc, service identities, and Cloud Tasks cleanup.

Use the single canonical deployment runbook in the repository [README](../README.md#deploy-to-gcp).
It contains the required bootstrap order and the `gitcrawl_agent_url` handoff to the Cloud Run
extension. Do not apply this directory independently without following that order.
