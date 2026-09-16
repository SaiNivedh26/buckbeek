# gitcrawl

`build-submit` is a small, Cloud Build-style source submission pipeline for codebase
analysis with Gemini on Vertex AI.

```text
tool submit [PATH]
  -> authenticated control function
  -> short-lived signed Cloud Storage PUT URL
  -> source archive upload
  -> storage-triggered analyzer function
  -> Gemini codebase analysis
  -> result JSON in Cloud Storage
```

The upload bucket is private, uniform-bucket-level access is enabled, objects expire
automatically, and both the CLI and analyzer reject `qwik.json` at any depth. The
control endpoint requires Google IAM authentication; it is not a public anonymous
endpoint.

## Deploy

Prerequisites: Terraform, `gcloud`, Python 3.10+, an active gcloud login, and permission
to create the resources in the target project.

```bash
cd build-submit
terraform init
terraform apply \
  -var='project_id=YOUR_PROJECT_ID' \
  -var='region=us-central1' \
  -var='invoker_member=user:YOU@example.com'
```

`invoker_member` can also be a group or service account, for example
`group:developers@example.com` or `serviceAccount:ci@PROJECT.iam.gserviceaccount.com`.


## Usage 
Install the local command and configure it from Terraform outputs:

```bash
./install.sh
tool configure --endpoint "$(terraform output -raw control_url)"
```

Then, from any source tree:

```bash
tool submit
tool submit ./another-project
tool submit --async
tool status SUBMISSION_ID
```

The CLI uses `gcloud auth print-identity-token` and Application Default Credentials
are not required locally. For automation, run the CLI as the service account granted
in `invoker_member`.

## Important variables

- `gemini_model`: defaults to `gemini-3-flash-preview`.
- `gemini_location`: defaults to `global`, independently of the function region.
- `max_context_bytes`: caps text sent to Gemini (default 750 KiB).
- `object_ttl_days`: deletes uploaded archives and results after 7 days by default.
- `additional_excludes`: extra archive patterns in addition to the CLI defaults.

The analysis is intentionally single-pass and bounded. For very large monorepos, a
production evolution would index chunks with embeddings and ask Gemini over retrieved
context rather than sending a single concatenated snapshot.

## Development checks

```bash
python3 -m unittest discover -s tests -v
terraform fmt -check -recursive
terraform validate
```

`terraform validate` requires `terraform init` first.
