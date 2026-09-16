# Hosted GitCrawl Terraform extension

This module intentionally references the existing build-submit bucket and analyzer service
account through data sources. It owns only the public Artifact Registry repository, the private
GitCrawl Cloud Run service, its deployer identity, and the additional least-privilege bindings.

Before applying this module, enable object versioning on the existing submissions bucket in the
original build-submit Terraform resource:

```hcl
versioning { enabled = true }
```

Also narrow the existing seven-day lifecycle condition to `matches_prefix = ["submissions/"]` so
objects under `repos/` retain their version history. Apply that change in the original Terraform
state; do not import or recreate the bucket here.

Pass `image_digest` as an immutable Artifact Registry URI (`...@sha256:...`). The runtime uses ADC
for Storage and Vertex AI and impersonates the dedicated revision deployer only while adding
0%-traffic tagged agent revisions to the single Cloud Run service. The untagged controller traffic
is preserved; each submission is dispatched to its recorded tag URL.
