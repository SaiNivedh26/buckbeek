# GitCrawl

Evaluate a GitHub repository against **your own rubric**.

`eval.md` is the canonical rubric name for hosted submissions. Existing `clause.md` files remain
supported by the library and local CLI.

You write the rubric as a `clause.md`: pillars, weights, criteria, score bands and hard
rules. GitCrawl turns it into an **Evaluation Plan** that you review and approve. Then it
evaluates any GitHub repository with that plan:

- **Tested collectors** gather facts deterministically, from repository files and the GitHub API.
- **Agents** answer only the questions that genuinely need judgement.
- **Code** decides caps, abstentions and the final arithmetic.

A default rubric and plan are bundled, so it works out of the box.

## Install

```bash
uv sync
cp .env.example .env
```

Add two keys to `.env`:

| Key | Needed for | Where |
|---|---|---|
| `GOOGLE_API_KEY` (or `GEMINI_API_KEY`) | `plan`, `evaluate` | Google AI Studio, free tier |
| `GITHUB_TOKEN` | GitHub data (issues, PRs, contributors, releases, CI runs) | GitHub → Settings → Developer settings → Fine-grained tokens, read-only public repositories |

Mistral and Groq are also supported: change `[models].provider` in `src/gitcrawl/config.toml`.

## Usage

```bash
# Facts only: collectors, no model calls, no cost
uv run gitcrawl facts imbaraniii/relink

# Evaluate with the bundled rubric and plan
uv run gitcrawl evaluate https://github.com/imbaraniii/relink

# Your own rubric
uv run gitcrawl plan my_clause.md -o my_plan.yaml     # one model call: draft plan
uv run gitcrawl plan approve my_plan.yaml             # after reviewing it
uv run gitcrawl evaluate owner/repo --plan my_plan.yaml
```

## Hosted operations: test, package, and deploy

This is the single runbook for the GitCrawl repository and the existing
**code-kitchen/build-submit** Terraform project. The runtime uses Vertex AI through ADC; never put
API keys or service-account JSON files in an image or submitted repository.

### Test a new project folder

The caller needs Cloud Run Invoker on the authenticated control function. For the current lab:

~~~bash
export PROJECT_ID="qwiklabs-gcp-01-f919029c9cda"
export REGION="us-central1"
export GITCRAWL_ENDPOINT="https://build-submit-control-2zjfzfxtdq-uc.a.run.app"
gcloud config set project "$PROJECT_ID"
gcloud auth login
~~~

To use the existing lab service account instead:

~~~bash
export GOOGLE_APPLICATION_CREDENTIALS="/home/sai-nivedh-26/code-kitchen/terr/qwik.json"
gcloud auth activate-service-account \
  terraform@qwiklabs-gcp-01-f919029c9cda.iam.gserviceaccount.com \
  --key-file="$GOOGLE_APPLICATION_CREDENTIALS"
~~~

Install the CLI, create the test repository, and submit it:

~~~bash
cd /home/sai-nivedh-26/gitcrawl
uv tool install --force .

mkdir -p /tmp/example-project
cd /tmp/example-project
git init
git remote add origin https://github.com/YOUR_ORG/YOUR_REPOSITORY.git
# Add the actual project files here.
git add .
git commit -m "Initial project"

gitcrawl submit --endpoint "$GITCRAWL_ENDPOINT" .
~~~

Without installing the CLI:

~~~bash
uv run --project /home/sai-nivedh-26/gitcrawl \
  gitcrawl submit --endpoint "$GITCRAWL_ENDPOINT" /tmp/example-project
~~~

A remote provides the stable host/owner/repository key. Without one, GitCrawl creates
**.gitcrawl-project-id**; preserve it to keep the same identity.

The first run normally follows:

~~~text
uploaded -> inspecting -> generating_eval -> planning -> deploying -> routing -> analyzing -> download -> complete
~~~

- Missing **eval.md** is generated and downloaded atomically into the submitted folder.
- Hosted **eval.md** starts with `Agent-ID: <uuid-v4>`. The UUID identifies the agent lineage;
  its normalized eval hash identifies an immutable version. The CLI atomically adds an ID to an
  existing legacy eval before upload.
- **plan.yaml** remains versioned in Cloud Storage and is never written locally.
- An unchanged rubric skips planning/deployment but still analyzes the submitted source.
- A changed rubric creates an approved plan and a new Cloud Run revision.
- Results live at **submissions/SUBMISSION_ID/result.json**.
- Durable versions live under **agents/AGENT-UUID/versions/EVAL-HASH/** and active state lives at
  **agents/AGENT-UUID/active.json**. Repository keys retain only an agent alias for audit.
- Each version is invoked through its own 0%-traffic Cloud Run tag URL. Concurrent repositories do
  not depend on or change the controller's default traffic.
- Submission source, status, result, and generated-download objects are deleted by Cloud Tasks ten
  minutes after completion or failure; durable agent artifacts remain.

To test all paths, submit without **eval.md**, edit the generated rubric and submit again, then
submit once more unchanged. The second run should deploy; the third should report
**deployed: false**.

### Package and push the agent

The image packages the Agno agent, Gemini model construction, rubric/plan lifecycle, evaluator,
and Cloud Run HTTP service. Set release variables:

~~~bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-central1"
export AR_REPOSITORY="gitcrawl"
export IMAGE_NAME="agent"
export IMAGE_TAG="0.1.0"
export IMAGE_URI="$REGION-docker.pkg.dev/$PROJECT_ID/$AR_REPOSITORY/$IMAGE_NAME"
~~~

After the Docker-format Artifact Registry repository exists:

~~~bash
gcloud auth configure-docker "$REGION-docker.pkg.dev"
cd /path/to/gitcrawl
docker build --platform linux/amd64 -t "$IMAGE_URI:$IMAGE_TAG" .
docker run --rm --entrypoint python "$IMAGE_URI:$IMAGE_TAG" \
  -c 'from gitcrawl.hosted.app import create_app; print("agent image OK")'
docker push "$IMAGE_URI:$IMAGE_TAG"

export IMAGE_DIGEST="$(
  gcloud artifacts docker images describe "$IMAGE_URI:$IMAGE_TAG" \
    --format='value(image_summary.digest)'
)"
export IMMUTABLE_IMAGE="$IMAGE_URI@$IMAGE_DIGEST"
printf '%s\n' "$IMMUTABLE_IMAGE"
~~~

Always deploy the immutable digest. Terraform makes only the image repository publicly readable;
the bucket, functions, Cloud Run service, and agent endpoints remain authenticated.

For a later code release, update the image and its self-deployment pin together, then use the same
**IMMUTABLE_IMAGE** in Terraform:

~~~bash
gcloud run services update gitcrawl-agent \
  --project="$PROJECT_ID" --region="$REGION" \
  --image="$IMMUTABLE_IMAGE" \
  --update-env-vars="GITCRAWL_IMAGE_DIGEST=$IMMUTABLE_IMAGE"
~~~

### Terraform ownership

Keep the two authoritative states separate:

| Stack | Directory | Owns |
|---|---|---|
| Submission pipeline | /path/to/code-kitchen/build-submit | APIs, buckets, control/analyzer functions, Eventarc, existing service accounts |
| GitCrawl extension | /path/to/gitcrawl/infra | Artifact Registry, Cloud Run agent, revision deployer, agent IAM |

The extension reads the existing submissions bucket and analyzer identity through data sources. It
must not recreate or import them.

The original submissions bucket must have versioning enabled and cleanup restricted to submission
objects:

~~~hcl
versioning { enabled = true }

lifecycle_rule {
  condition {
    age            = var.object_ttl_days
    matches_prefix = ["submissions/"]
  }
  action { type = "Delete" }
}
~~~

Update the original function sources when necessary:

~~~bash
cp -R /path/to/gitcrawl/pipeline_functions/control/. \
  /path/to/code-kitchen/build-submit/functions/control/
cp -R /path/to/gitcrawl/pipeline_functions/analyzer/. \
  /path/to/code-kitchen/build-submit/functions/analyzer/
~~~

The analyzer's **GITCRAWL_AGENT_URL** belongs in the original Terraform stack and must equal the
extension's **agent_url** output.

Plan the original stack first:

~~~bash
terraform -chdir=/path/to/code-kitchen/build-submit init
terraform -chdir=/path/to/code-kitchen/build-submit plan \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="invoker_member=user:YOU@example.com"
~~~

Function source updates may replace content-addressed ZIP objects. The plan must not replace or
duplicate buckets, functions, Eventarc resources, or service accounts.

Apply the extension against the existing resources:

~~~bash
export SUBMISSIONS_BUCKET="$PROJECT_ID-build-submit"
export ANALYZER_SA="build-submit-analyzer@$PROJECT_ID.iam.gserviceaccount.com"

terraform -chdir=/path/to/gitcrawl/infra init
terraform -chdir=/path/to/gitcrawl/infra plan -out=/tmp/gitcrawl.tfplan \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="submissions_bucket_name=$SUBMISSIONS_BUCKET" \
  -var="analyzer_service_account_email=$ANALYZER_SA" \
  -var="invoker_member=serviceAccount:$ANALYZER_SA" \
  -var="image_digest=$IMMUTABLE_IMAGE"
terraform -chdir=/path/to/gitcrawl/infra apply /tmp/gitcrawl.tfplan
terraform -chdir=/path/to/gitcrawl/infra output -raw agent_url
~~~

Put that output in **GITCRAWL_AGENT_URL** in the analyzer function's Terraform environment, then
plan and apply the original stack.

### Brand-new project bootstrap order

1. Apply **code-kitchen/build-submit** first, using a temporary valid analyzer URL. Do not submit
   repositories yet.
2. Bootstrap only the registry from the extension:

~~~bash
terraform -chdir=/path/to/gitcrawl/infra init
terraform -chdir=/path/to/gitcrawl/infra apply \
  -target=google_artifact_registry_repository.gitcrawl \
  -target=google_artifact_registry_repository_iam_member.public_reader \
  -var="project_id=$PROJECT_ID" \
  -var="region=$REGION" \
  -var="submissions_bucket_name=$PROJECT_ID-build-submit" \
  -var="analyzer_service_account_email=build-submit-analyzer@$PROJECT_ID.iam.gserviceaccount.com" \
  -var="invoker_member=serviceAccount:build-submit-analyzer@$PROJECT_ID.iam.gserviceaccount.com" \
  -var="image_digest=$REGION-docker.pkg.dev/$PROJECT_ID/gitcrawl/agent@sha256:bootstrap"
~~~

3. Build/push the image and resolve **IMMUTABLE_IMAGE**.
4. Run a normal untargeted extension plan/apply with the real digest.
5. Replace the temporary analyzer URL with the real **agent_url** and reapply the original stack.
6. Run normal plans in both directories; both must say **No changes**.

Targeted apply is only for initial registry bootstrap, never routine deployments.

### Verify

~~~bash
terraform -chdir=/path/to/code-kitchen/build-submit validate
terraform -chdir=/path/to/gitcrawl/infra validate

gcloud run services describe gitcrawl-agent \
  --project="$PROJECT_ID" --region="$REGION" \
  --format='yaml(status.latestCreatedRevisionName,status.latestReadyRevisionName,status.traffic)'

gcloud storage cat \
  "gs://$SUBMISSIONS_BUCKET/agents/AGENT-UUID/active.json"
~~~

The controller keeps default traffic while agent revisions use distinct tags at 0%. **active.json**
must contain the expected tagged revision URL, hashes, and immutable image digest. Versioned
rubric/plan objects remain durable even when an inactive Cloud Run revision is pruned and later
recreated on demand.

`evaluate` prints a score table, then a few lines per pillar explaining how the score was reached:
- the reasoning;
- any hard rule that capped the score;
- criteria that weren't measurable;
- whether the repository tried to influence its own evaluation.

`--json report.json` also writes the full report, including every fact and judgement.

See [`docs/clause.md`](docs/clause.md) for how to write a rubric.

## How it works

```
PLAN (once per clause.md)                          EVALUATE (per repository)
clause.md → parse (code) → planner (model)         preflight: plan approved and valid? (code)
  → validate (code) → plan.yaml                    → collectors: facts (code, cached)
  → you review → plan approve                      → hard rules: cap / not assessed (code)
                                                   → judgement agents (models + tools)
                                                   → pillar scorers (models, isolated)
                                                   → caps, abstention, weighted total (code)
```

**Each criterion in your rubric becomes one of three things:**
- **Measured:** backed by a collector, for example `ci.config`, `tests.mapping` or `github.issues`.
- **Judgement:** a focused question for an agent, for example "are the tests meaningful?".
- **Not measurable:** excluded from the score with a stated reason, never guessed.

**Agents are grouped by the evidence they need, not by pillar.** One agent reads test code for
every test-related question, so files aren't re-read across pillars. Scorers stay one per pillar,
so a strong pillar can't lift a weak one.

**Deterministic where it must be.** The planner can only choose collectors and fill in their
parameters. It never writes code. Hard rules are small expressions that code parses and evaluates.
Only the band and score within a pillar come from a model, and code still enforces the caps
afterwards.

**Checked evidence.** An agent's citations are compared with the files and threads it actually
opened, and unverified citations are reported.

**Collectors** (see `gitcrawl facts`):

| Area | Collectors |
|---|---|
| Files | `repo.inventory`, `file.exists`, `file.count`, `file.contains`, `manifest.field` |
| CI | `ci.config` (follows reusable workflows, composite actions, package scripts, Makefile targets) |
| Tests | `tests.inventory`, `tests.mapping` (static test→source mapping), `tests.coverage` |
| Code | `code.structure`, `code.imports` |
| GitHub API | `github.repo`, `github.issues`, `github.pull_requests`, `github.contributors`, `github.releases`, `github.workflow_runs` |

Design rationale: [`docs/design.md`](docs/design.md).

## Configuration

`src/gitcrawl/config.toml` holds:
- model ids;
- requests-per-minute pacing per provider;
- agent tool budgets per evidence domain;
- GitHub API windows;
- cache TTLs.

Any value can be overridden with a `GITCRAWL_` environment variable, for example
`GITCRAWL_MODELS__SCORER`. The rubric itself is never configured here: it comes from `clause.md`.

Results are cached in `~/.cache/gitcrawl/gitcrawl.db`.
- **Repeat runs:** served from cache.
- **Facts from files:** keyed by commit.
- **GitHub facts:** refreshed daily.
- **Model outputs:** keyed by their exact inputs.
- **Failures:** never cached.

## Development

```bash
uv run pytest tests/ -q        # fully offline: agents and GitHub are mocked
uv run ruff check src/ tests/
```

`tests/fixtures/` holds small synthetic repositories. `ci_rich/` has real CI (a reusable workflow,
a coverage gate, a Makefile lint target) and a deliberately untested module. `injection/` has a
README that asks evaluators for 10/10.

See [`CLAUDE.md`](CLAUDE.md) before changing anything structural.

## Limits

- **GitHub repositories only.**
- **Scores are not calibrated yet.** Treat the cited facts as the trustworthy part and the exact
  number as an estimate.
- **Test mapping is static.** It shows which modules any test imports or is named after, not
  runtime coverage. Runtime coverage is only reported when a coverage report is committed.
- **Adoption signals are not measurable.** Dependents and blog mentions aren't available, so the
  default rubric reports them as excluded.
