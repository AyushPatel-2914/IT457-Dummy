# S1 lift-and-shift: the unchanged monolith + Postgres containers on ONE EC2 instance in ONE AZ.
# terraform apply -var image=<ecr-url>:latest -var instance_profile=<name> -var allowed_cidr=<your-ip>/32
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "mini-netflix", stage = "s1" } }
}

variable "region" { default = "us-east-1" }
variable "az" { default = "us-east-1a" }
variable "instance_type" { default = "t3.micro" }
variable "image" { description = "Full image URI, e.g. 123.dkr.ecr.us-east-1.amazonaws.com/mini-netflix:latest" }
variable "instance_profile" { description = "Instance profile name (output of infra/shared)" }
variable "allowed_cidr" {
  description = "Who may reach port 80 (your load generator's IP /32)"
  default     = "0.0.0.0/0"
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_vpc" "default" { default = true }

data "aws_subnet" "az" {
  vpc_id            = data.aws_vpc.default.id
  availability_zone = var.az
  default_for_az    = true
}

resource "aws_security_group" "s1" {
  name   = "mini-netflix-s1"
  vpc_id = data.aws_vpc.default.id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = [var.allowed_cidr]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ssm_parameter.al2023.value
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnet.az.id
  vpc_security_group_ids      = [aws_security_group.s1.id]
  iam_instance_profile        = var.instance_profile
  associate_public_ip_address = true
  user_data_replace_on_change = true
  user_data = templatefile("${path.module}/user_data.sh", {
    region   = var.region
    registry = split("/", var.image)[0]
    image    = var.image
  })
  metadata_options { http_tokens = "required" }
  tags = { Name = "mini-netflix-s1" }
}

output "url" { value = "http://${aws_instance.app.public_ip}" }
output "instance_id" { value = aws_instance.app.id }
