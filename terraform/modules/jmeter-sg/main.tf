# =============================================================================
# JMeter Security Group Module
# =============================================================================

variable "name" {
  description = "Security group name"
  type        = string
}

variable "vpc_id" {
  description = "VPC ID (empty for default VPC)"
  type        = string
  default     = ""
}

variable "environment" {
  description = "Environment tag"
  type        = string
}

variable "allowed_ssh_cidrs" {
  description = "CIDRs allowed for SSH"
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

# Get default VPC if not specified
data "aws_vpc" "default" {
  count   = var.vpc_id == "" ? 1 : 0
  default = true
}

locals {
  vpc_id = var.vpc_id != "" ? var.vpc_id : data.aws_vpc.default[0].id
}

resource "aws_security_group" "jmeter" {
  name        = var.name
  description = "Security group for JMeter distributed testing"
  vpc_id      = local.vpc_id
  
  tags = {
    Name        = var.name
    Environment = var.environment
  }
}

# SSH access
resource "aws_security_group_rule" "ssh" {
  type              = "ingress"
  from_port         = 22
  to_port           = 22
  protocol          = "tcp"
  cidr_blocks       = var.allowed_ssh_cidrs
  description       = "SSH access"
  security_group_id = aws_security_group.jmeter.id
}

# JMeter RMI Registry
resource "aws_security_group_rule" "rmi_registry" {
  type              = "ingress"
  from_port         = 1099
  to_port           = 1099
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "JMeter RMI registry"
  security_group_id = aws_security_group.jmeter.id
}

# JMeter Server Port
resource "aws_security_group_rule" "server_port" {
  type              = "ingress"
  from_port         = 50000
  to_port           = 50000
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "JMeter server port"
  security_group_id = aws_security_group.jmeter.id
}

# JMeter Local Port
resource "aws_security_group_rule" "local_port" {
  type              = "ingress"
  from_port         = 50001
  to_port           = 50001
  protocol          = "tcp"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "JMeter local port"
  security_group_id = aws_security_group.jmeter.id
}

# Internal communication (all traffic within security group)
resource "aws_security_group_rule" "internal" {
  type                     = "ingress"
  from_port                = 0
  to_port                  = 0
  protocol                 = "-1"
  source_security_group_id = aws_security_group.jmeter.id
  description              = "Internal communication"
  security_group_id        = aws_security_group.jmeter.id
}

# Egress - allow all outbound
resource "aws_security_group_rule" "egress" {
  type              = "egress"
  from_port         = 0
  to_port           = 0
  protocol          = "-1"
  cidr_blocks       = ["0.0.0.0/0"]
  description       = "Allow all outbound"
  security_group_id = aws_security_group.jmeter.id
}

output "security_group_id" {
  value = aws_security_group.jmeter.id
}

output "security_group_name" {
  value = aws_security_group.jmeter.name
}
