# =============================================================================
# JMeter Distributed Framework - Terraform Variables
# =============================================================================

variable "aws_region" {
  description = "AWS region for resources"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name (e.g., dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name used for resource naming"
  type        = string
  default     = "jmeter-distributed"
}

variable "vpc_id" {
  description = "VPC ID for security group. Leave empty to use default VPC."
  type        = string
  default     = ""
}

variable "results_retention_days" {
  description = "Number of days to retain results in S3"
  type        = number
  default     = 90
}

variable "allowed_ssh_cidrs" {
  description = "CIDR blocks allowed for SSH access"
  type        = list(string)
  default     = ["0.0.0.0/0"]  # Restrict in production!
}

variable "key_pair_name" {
  description = "Name of SSH key pair for EC2 instances"
  type        = string
  default     = "jmeter-framework-key"
}

variable "create_ecr_repo" {
  description = "Whether to create an ECR repository for JMeter image"
  type        = bool
  default     = false
}
