# Shared, long-lived pieces: container registry, $5 budget alert, EC2 instance profile.
# Create once: terraform init && terraform apply -var budget_email=you@example.com
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "mini-netflix" } }
}

variable "region" { default = "us-east-1" }
variable "budget_email" {
  description = "Email for the AWS Budget alert. Leave empty to skip (e.g. AWS Academy blocks Budgets)."
  default     = ""
}
variable "existing_instance_profile" {
  description = "Use an existing instance profile instead of creating one (AWS Academy: LabInstanceProfile)."
  default     = ""
}

resource "aws_ecr_repository" "app" {
  name         = "mini-netflix"
  force_delete = true
}

resource "aws_budgets_budget" "cap" {
  count        = var.budget_email == "" ? 0 : 1
  name         = "mini-netflix-5usd"
  budget_type  = "COST"
  limit_amount = "5"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
}

# Instances need to pull from ECR and accept SSM commands (fault injection, no SSH needed).
resource "aws_iam_role" "instance" {
  count = var.existing_instance_profile == "" ? 1 : 0
  name  = "mini-netflix-instance"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "instance" {
  for_each = var.existing_instance_profile == "" ? toset([
    "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    "arn:aws:iam::aws:policy/AmazonEC2ContainerRegistryReadOnly",
  ]) : toset([])
  role       = aws_iam_role.instance[0].name
  policy_arn = each.value
}

resource "aws_iam_instance_profile" "instance" {
  count = var.existing_instance_profile == "" ? 1 : 0
  name  = "mini-netflix-instance"
  role  = aws_iam_role.instance[0].name
}

output "ecr_repository_url" { value = aws_ecr_repository.app.repository_url }
output "instance_profile_name" {
  value = var.existing_instance_profile != "" ? var.existing_instance_profile : aws_iam_instance_profile.instance[0].name
}
