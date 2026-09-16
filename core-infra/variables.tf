variable "project_id" {
  description = "Google Cloud project in which to deploy the pipeline."
  type        = string
}

variable "region" {
  description = "Region for Cloud Functions and the source bucket."
  type        = string
  default     = "us-central1"
}

variable "invoker_member" {
  description = "IAM member allowed to invoke the control function (user:, group:, or serviceAccount:)."
  type        = string
}

variable "gemini_location" {
  description = "Vertex AI location used by the Google Gen AI SDK."
  type        = string
  default     = "global"
}

variable "gemini_model" {
  description = "Gemini model used for repository analysis."
  type        = string
  default     = "gemini-3-flash-preview"
}

variable "max_context_bytes" {
  description = "Maximum UTF-8 source context included in a single Gemini request."
  type        = number
  default     = 768000
}

variable "max_archive_bytes" {
  description = "Maximum accepted compressed upload size."
  type        = number
  default     = 52428800
}

variable "object_ttl_days" {
  description = "Days after which uploaded archives and results are deleted."
  type        = number
  default     = 7
}
