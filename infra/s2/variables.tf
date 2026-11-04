variable "region" { default = "us-east-1" }
variable "azs" { default = ["us-east-1a", "us-east-1b"] }
variable "instance_type" { default = "t3.micro" }
variable "image" { description = "Full image URI, e.g. 123.dkr.ecr.us-east-1.amazonaws.com/mini-netflix:latest" }
variable "instance_profile" { description = "Instance profile name (output of infra/shared)" }
variable "allowed_cidr" {
  description = "Who may reach the ALB (your load generator's IP /32)"
  default     = "0.0.0.0/0"
}
variable "min_size" { default = 2 }
variable "desired_capacity" { default = 2 }
variable "max_size" { default = 4 }
variable "cpu_target" { default = 50 }
variable "db_instance_class" { default = "db.t3.micro" }
variable "db_multi_az" { default = false }
variable "breaker" {
  description = "on = circuit breaker + fallback for the recommendations call; off = naive call (E3/E4 comparison)"
  default     = "on"
}
variable "enable_fis" {
  description = "Create AWS Fault Injection Service templates (needs IAM role creation; AWS Academy may block it)"
  default     = false
}
