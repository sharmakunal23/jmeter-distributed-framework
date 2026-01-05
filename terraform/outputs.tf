# =============================================================================
# JMeter Distributed Framework - Terraform Outputs
# =============================================================================

output "s3_bucket_name" {
  description = "Name of the S3 bucket for results"
  value       = aws_s3_bucket.results.id
}

output "s3_bucket_arn" {
  description = "ARN of the S3 bucket"
  value       = aws_s3_bucket.results.arn
}

output "iam_role_arn" {
  description = "ARN of the IAM role for EC2 instances"
  value       = aws_iam_role.jmeter_ec2.arn
}

output "instance_profile_name" {
  description = "Name of the IAM instance profile"
  value       = aws_iam_instance_profile.jmeter.name
}

output "security_group_id" {
  description = "ID of the JMeter security group"
  value       = module.security_group.security_group_id
}

output "ecr_repository_url" {
  description = "URL of the ECR repository (if created)"
  value       = var.create_ecr_repo ? aws_ecr_repository.jmeter[0].repository_url : null
}

# Generate framework.yaml snippet
output "framework_config_snippet" {
  description = "Configuration snippet for framework.yaml"
  value       = <<-EOT
    # Add these values to config/framework.yaml
    aws:
      region: "${data.aws_region.current.name}"
      ec2:
        key_pair_name: "${var.key_pair_name}"
        security_group:
          name: "${module.security_group.security_group_name}"
      s3:
        bucket_name: "${aws_s3_bucket.results.id}"
      iam:
        instance_profile_name: "${aws_iam_instance_profile.jmeter.name}"
    ${var.create_ecr_repo ? "docker:\n      registry: \"${aws_ecr_repository.jmeter[0].repository_url}\"" : ""}
  EOT
}
