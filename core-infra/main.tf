locals {
  services = toset([
    "aiplatform.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudfunctions.googleapis.com",
    "cloudtasks.googleapis.com",
    "eventarc.googleapis.com",
    "iamcredentials.googleapis.com",
    "logging.googleapis.com",
    "pubsub.googleapis.com",
    "run.googleapis.com",
    "storage.googleapis.com",
  ])
}

data "google_project" "current" {
  project_id = var.project_id
}

resource "google_project_service" "required" {
  for_each           = local.services
  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "submissions" {
  name                        = "${var.project_id}-build-submit"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    condition {
      age            = var.object_ttl_days
      matches_prefix = ["submissions/"]
    }
    action { type = "Delete" }
  }

  depends_on = [google_project_service.required]
}

resource "google_storage_bucket" "function_source" {
  name                        = "${var.project_id}-build-submit-functions"
  location                    = var.region
  uniform_bucket_level_access = true
  force_destroy               = false

  depends_on = [google_project_service.required]
}

resource "google_service_account" "control" {
  account_id   = "build-submit-control"
  display_name = "Build Submit control function"
}

resource "google_service_account" "analyzer" {
  account_id   = "build-submit-analyzer"
  display_name = "Build Submit analyzer function"
}

resource "google_service_account" "cleanup" {
  account_id   = "build-submit-cleanup"
  display_name = "Build Submit scheduled cleanup caller"
}

resource "google_cloud_tasks_queue" "cleanup" {
  name     = "build-submit-cleanup"
  location = var.region

  retry_config {
    max_attempts       = 5
    max_retry_duration = "3600s"
  }

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "control_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.control.email}"
}

resource "google_project_iam_member" "analyzer_tasks_enqueuer" {
  project = var.project_id
  role    = "roles/cloudtasks.enqueuer"
  member  = "serviceAccount:${google_service_account.analyzer.email}"
}

resource "google_service_account_iam_member" "control_acts_as_cleanup" {
  service_account_id = google_service_account.cleanup.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.control.email}"
}

resource "google_service_account_iam_member" "analyzer_acts_as_cleanup" {
  service_account_id = google_service_account.cleanup.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.analyzer.email}"
}

resource "google_storage_bucket_iam_member" "control_objects" {
  bucket = google_storage_bucket.submissions.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.control.email}"
}

resource "google_storage_bucket_iam_member" "analyzer_objects" {
  bucket = google_storage_bucket.submissions.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.analyzer.email}"
}

# generate_signed_url uses the IAM Credentials signBlob API with attached
# service-account credentials, so the control identity must be able to sign as itself.
resource "google_service_account_iam_member" "control_signer" {
  service_account_id = google_service_account.control.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${google_service_account.control.email}"
}

resource "google_project_iam_member" "analyzer_vertex" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.analyzer.email}"
}

resource "google_project_iam_member" "analyzer_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.analyzer.email}"
}

resource "google_project_iam_member" "analyzer_event_receiver" {
  project = var.project_id
  role    = "roles/eventarc.eventReceiver"
  member  = "serviceAccount:${google_service_account.analyzer.email}"
}

# Eventarc delivers the event to the analyzer's underlying Cloud Run service
# using this trigger identity.
resource "google_project_iam_member" "analyzer_run_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.analyzer.email}"
}

# Fresh projects can create the Eventarc service identity before its automatic
# project-level service-agent grant has propagated. Managing it explicitly makes
# the first deployment deterministic.
resource "google_project_iam_member" "eventarc_service_agent" {
  project = var.project_id
  role    = "roles/eventarc.serviceAgent"
  member  = "serviceAccount:service-${data.google_project.current.number}@gcp-sa-eventarc.iam.gserviceaccount.com"
}

# Eventarc's Cloud Storage trigger requires the project's Storage service agent
# to publish the object-finalized notification.
resource "google_project_iam_member" "storage_pubsub" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:service-${data.google_project.current.number}@gs-project-accounts.iam.gserviceaccount.com"
}

data "archive_file" "control" {
  type        = "zip"
  source_dir  = "${path.module}/functions/control"
  output_path = "${path.module}/.terraform/control.zip"
}

data "archive_file" "analyzer" {
  type        = "zip"
  source_dir  = "${path.module}/functions/analyzer"
  output_path = "${path.module}/.terraform/analyzer.zip"
}

resource "google_storage_bucket_object" "control_source" {
  name   = "control-${data.archive_file.control.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.control.output_path
}

resource "google_storage_bucket_object" "analyzer_source" {
  name   = "analyzer-${data.archive_file.analyzer.output_md5}.zip"
  bucket = google_storage_bucket.function_source.name
  source = data.archive_file.analyzer.output_path
}

resource "google_cloudfunctions2_function" "control" {
  name     = "build-submit-control"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "control"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.control_source.name
      }
    }
  }

  service_config {
    available_memory      = "256M"
    timeout_seconds       = 60
    max_instance_count    = 5
    service_account_email = google_service_account.control.email
    environment_variables = {
      SUBMISSIONS_BUCKET      = google_storage_bucket.submissions.name
      MAX_ARCHIVE_BYTES       = tostring(var.max_archive_bytes)
      CLEANUP_QUEUE           = google_cloud_tasks_queue.cleanup.id
      CLEANUP_SERVICE_ACCOUNT = google_service_account.cleanup.email
    }
  }

  depends_on = [google_project_service.required, google_service_account_iam_member.control_signer]
}

resource "google_cloud_run_service_iam_member" "control_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.control.name
  role     = "roles/run.invoker"
  member   = var.invoker_member
}

resource "google_cloud_run_service_iam_member" "cleanup_invoker" {
  project  = var.project_id
  location = var.region
  service  = google_cloudfunctions2_function.control.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cleanup.email}"
}

resource "google_cloudfunctions2_function" "analyzer" {
  name     = "build-submit-analyzer"
  location = var.region

  build_config {
    runtime     = "python312"
    entry_point = "analyze_submission"
    source {
      storage_source {
        bucket = google_storage_bucket.function_source.name
        object = google_storage_bucket_object.analyzer_source.name
      }
    }
  }

  service_config {
    available_memory      = "1Gi"
    timeout_seconds       = 540
    max_instance_count    = 5
    service_account_email = google_service_account.analyzer.email
    environment_variables = {
      SUBMISSIONS_BUCKET      = google_storage_bucket.submissions.name
      GITCRAWL_AGENT_URL      = var.gitcrawl_agent_url
      CLEANUP_QUEUE           = google_cloud_tasks_queue.cleanup.id
      CLEANUP_URL             = google_cloudfunctions2_function.control.service_config[0].uri
      CLEANUP_SERVICE_ACCOUNT = google_service_account.cleanup.email
    }
  }

  event_trigger {
    trigger_region        = var.region
    event_type            = "google.cloud.storage.object.v1.finalized"
    retry_policy          = "RETRY_POLICY_RETRY"
    service_account_email = google_service_account.analyzer.email
    event_filters {
      attribute = "bucket"
      value     = google_storage_bucket.submissions.name
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.storage_pubsub,
    google_project_iam_member.analyzer_vertex,
    google_project_iam_member.analyzer_event_receiver,
    google_project_iam_member.analyzer_run_invoker,
    google_project_iam_member.eventarc_service_agent,
  ]
}

output "control_url" {
  description = "Authenticated endpoint consumed by the tool CLI."
  value       = google_cloudfunctions2_function.control.service_config[0].uri
}

output "submissions_bucket" {
  value = google_storage_bucket.submissions.name
}
