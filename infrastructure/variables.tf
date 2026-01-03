variable "aws_region" {
  default = "eu-central-1"
  type    = string
}

variable "stage" {
  default = "dev"
  type    = string
}

variable "anthropic_api_key" {
  type = string
}

variable "app_name" {
  default = "code-sheriff"
  type    = string
}

variable "architecture" {
  default = "x86_64"
  type    = string
}

variable "artifact_bucket" {
  type    = string
}

variable "content_hash" {
  type    = string
}

variable "debug" {
  default = false
  type    = bool
}

variable "github_token" {
  type = string
}

variable "github_webhook_secret" {
  default = ""
  type    = string
}

variable "log_level" {
  default = "INFO"
  type    = string
}

variable "power_tools_service_name" {
  default = "code-sheriff"
  type    = string
}

variable "rate_limit_duration_in_seconds" {
  default = 60
  type    = number
}

variable "rate_limit_requests" {
  default = 60
  type    = number
}

variable "rate_limiting" {
  default = true
  type    = bool
}

variable "requirements_layer_content_hash" {
  type = string
}

variable "tags" {
  type = map(string)
}
