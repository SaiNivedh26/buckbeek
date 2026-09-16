# Existing resources remain owned by the build-submit Terraform state. Data
# references make accidental duplicate buckets/service accounts impossible.
data "google_storage_bucket" "submissions" {
  name = var.submissions_bucket_name
}

data "google_service_account" "runtime" {
  account_id = var.analyzer_service_account_email
}

resource "google_artifact_registry_repository" "gitcrawl" {
  location      = var.region
  repository_id = "gitcrawl"
  description   = "Public immutable GitCrawl agent images"
  format        = "DOCKER"
}

resource "google_artifact_registry_repository_iam_member" "public_reader" {
  project    = var.project_id
  location   = google_artifact_registry_repository.gitcrawl.location
  repository = google_artifact_registry_repository.gitcrawl.name
  role       = "roles/artifactregistry.reader"
  member     = "allUsers"
}

resource "google_service_account" "deployer" {
  account_id   = "gitcrawl-revision-deployer"
  display_name = "GitCrawl Cloud Run revision deployer"
}

resource "google_cloud_run_v2_service" "agent" {
  name                = var.service_name
  location            = var.region
  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = data.google_service_account.runtime.email
    timeout         = "900s"

    scaling {
      min_instance_count = 0
      max_instance_count = 5
    }

    containers {
      image = var.image_digest

      resources {
        limits = {
          cpu    = "2"
          memory = "2Gi"
        }
      }

      env {
        name  = "SUBMISSIONS_BUCKET"
        value = data.google_storage_bucket.submissions.name
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
      env {
        name  = "GOOGLE_CLOUD_LOCATION"
        value = "global"
      }
      env {
        name  = "CLOUD_RUN_REGION"
        value = var.region
      }
      env {
        name  = "CLOUD_RUN_SERVICE"
        value = var.service_name
      }
      env {
        name  = "CLOUD_RUN_DEPLOYER_SERVICE_ACCOUNT"
        value = google_service_account.deployer.email
      }
      env {
        name  = "GITCRAWL_GOOGLE_VERTEXAI"
        value = "true"
      }
      env {
        name  = "GITCRAWL_IMAGE_DIGEST"
        value = var.image_digest
      }
      env {
        name  = "GITCRAWL_MODELS__PROVIDER"
        value = "google"
      }
      env {
        name  = "GITCRAWL_MODELS__INVESTIGATOR"
        value = var.gemini_model
      }
      env {
        name  = "GITCRAWL_MODELS__SCORER"
        value = var.gemini_model
      }
      env {
        name  = "GITCRAWL_MODELS__PLANNER"
        value = var.gemini_model
      }

      startup_probe {
        http_get {
          path = "/readyz"
        }
        initial_delay_seconds = 1
        timeout_seconds       = 10
        period_seconds        = 10
        failure_threshold     = 12
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # Revision-specific rubric and plan pins are updated by the lifecycle
  # deployer. Terraform owns the bootstrap environment but must not roll a
  # successfully activated revision back to those bootstrap values.
  lifecycle {
    ignore_changes = [
      client,
      client_version,
      scaling,
      template[0].containers[0].env,
      traffic,
    ]
  }
}

resource "google_cloud_run_v2_service_iam_member" "private_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.agent.location
  name     = google_cloud_run_v2_service.agent.name
  role     = "roles/run.invoker"
  member   = var.invoker_member
}

resource "google_cloud_run_v2_service_iam_member" "revision_deployer" {
  project  = var.project_id
  location = google_cloud_run_v2_service.agent.location
  name     = google_cloud_run_v2_service.agent.name
  role     = "roles/run.developer"
  member   = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "deployer_acts_as_runtime" {
  service_account_id = data.google_service_account.runtime.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_service_account_iam_member" "runtime_impersonates_deployer" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${data.google_service_account.runtime.email}"
}

output "agent_url" {
  value = google_cloud_run_v2_service.agent.uri
}

output "public_image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.gitcrawl.repository_id}"
}
