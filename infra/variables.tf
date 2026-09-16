variable "project_id" {
  description = "Project containing the existing build-submit pipeline."
  type        = string
}

variable "region" {
  type    = string
  default = "us-central1"
}

variable "submissions_bucket_name" {
  description = "Existing Terraform-managed build-submit bucket; this module references rather than creates it."
  type        = string
}

variable "analyzer_service_account_email" {
  description = "Existing build-submit analyzer service account used as the Cloud Run runtime identity."
  type        = string
}

variable "image_digest" {
  description = "Immutable public Artifact Registry image URI including @sha256 digest."
  type        = string

  validation {
    condition     = strcontains(var.image_digest, "@sha256:")
    error_message = "image_digest must be an immutable image URI containing @sha256:."
  }
}

variable "service_name" {
  type    = string
  default = "gitcrawl-agent"
}

variable "gemini_model" {
  type    = string
  default = "gemini-3.5-flash-lite"
}

variable "invoker_member" {
  description = "Existing analyzer/Eventarc identity allowed to invoke the private service."
  type        = string
}
