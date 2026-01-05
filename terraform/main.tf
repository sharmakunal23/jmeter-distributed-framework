# =============================================================================
# JMeter Distributed Framework - Terraform Configuration
# =============================================================================
# Creates persistent infrastructure:
# - S3 bucket for results storage
# - IAM role and instance profile for EC2
# - Security group for JMeter communication
# =============================================================================

terraform {
  required_version = ">= 1.0"
  
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
  
  # Uncomment to use S3 backend for state
  # backend "s3" {
  #   bucket = "your-terraform-state-bucket"
  #   key    = "jmeter-framework/terraform.tfstate"
  #   region = "us-east-1"
  # }
}

provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      Project     = "jmeter-distributed-framework"
      ManagedBy   = "terraform"
      Environment = var.environment
    }
  }
}

# -----------------------------------------------------------------------------
# Data Sources
# -----------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# -----------------------------------------------------------------------------
# S3 Bucket for Results
# -----------------------------------------------------------------------------

resource "aws_s3_bucket" "results" {
  bucket = "${var.project_name}-results-${data.aws_caller_identity.current.account_id}"
  
  tags = {
    Name = "JMeter Results Storage"
  }
}

resource "aws_s3_bucket_versioning" "results" {
  bucket = aws_s3_bucket.results.id
  
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "results" {
  bucket = aws_s3_bucket.results.id
  
  rule {
    id     = "expire-old-results"
    status = "Enabled"
    
    filter {
      prefix = "results/"
    }
    
    expiration {
      days = var.results_retention_days
    }
    
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "results" {
  bucket = aws_s3_bucket.results.id
  
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# -----------------------------------------------------------------------------
# IAM Role for EC2 Instances
# -----------------------------------------------------------------------------

resource "aws_iam_role" "jmeter_ec2" {
  name = "${var.project_name}-ec2-role"
  
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "jmeter_s3" {
  name = "${var.project_name}-s3-access"
  role = aws_iam_role.jmeter_ec2.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket",
          "s3:DeleteObject"
        ]
        Resource = [
          aws_s3_bucket.results.arn,
          "${aws_s3_bucket.results.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "jmeter_ecr" {
  name = "${var.project_name}-ecr-access"
  role = aws_iam_role.jmeter_ec2.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "ecr:GetAuthorizationToken",
          "ecr:BatchCheckLayerAvailability",
          "ecr:GetDownloadUrlForLayer",
          "ecr:BatchGetImage"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "jmeter_cloudwatch" {
  name = "${var.project_name}-cloudwatch"
  role = aws_iam_role.jmeter_ec2.id
  
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents",
          "cloudwatch:PutMetricData"
        ]
        Resource = "*"
      }
    ]
  })
}

resource "aws_iam_instance_profile" "jmeter" {
  name = "${var.project_name}-ec2-profile"
  role = aws_iam_role.jmeter_ec2.name
}

# -----------------------------------------------------------------------------
# Security Group
# -----------------------------------------------------------------------------

module "security_group" {
  source = "./modules/jmeter-sg"
  
  name        = "${var.project_name}-sg"
  vpc_id      = var.vpc_id
  environment = var.environment
  
  allowed_ssh_cidrs = var.allowed_ssh_cidrs
}

# -----------------------------------------------------------------------------
# ECR Repository (Optional)
# -----------------------------------------------------------------------------

resource "aws_ecr_repository" "jmeter" {
  count = var.create_ecr_repo ? 1 : 0
  
  name                 = var.project_name
  image_tag_mutability = "MUTABLE"
  
  image_scanning_configuration {
    scan_on_push = true
  }
  
  tags = {
    Name = "JMeter Docker Image"
  }
}

resource "aws_ecr_lifecycle_policy" "jmeter" {
  count = var.create_ecr_repo ? 1 : 0
  
  repository = aws_ecr_repository.jmeter[0].name
  
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Keep last 10 images"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 10
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}

# -----------------------------------------------------------------------------
# SSH Key Pair (Optional - import existing)
# -----------------------------------------------------------------------------

# Uncomment to create a new key pair
# resource "aws_key_pair" "jmeter" {
#   key_name   = var.key_pair_name
#   public_key = file("~/.ssh/${var.key_pair_name}.pub")
# }
