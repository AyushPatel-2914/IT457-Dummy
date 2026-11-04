# S2 refactor: three services on every instance, ALB path routing, Auto Scaling Group across two
# AZs, managed Postgres (RDS). Optional AWS FIS experiment templates in fis.tf (enable_fis = true).
# terraform apply -var image=<ecr-url>:latest -var instance_profile=<name> -var allowed_cidr=<your-ip>/32
terraform {
  required_version = ">= 1.5"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 5.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "mini-netflix", stage = "s2" } }
}

data "aws_ssm_parameter" "al2023" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

data "aws_vpc" "default" { default = true }

# The default VPC's public subnets: no NAT gateway needed, which keeps the cost near zero.
data "aws_subnet" "az" {
  for_each          = toset(var.azs)
  vpc_id            = data.aws_vpc.default.id
  availability_zone = each.value
  default_for_az    = true
}

locals {
  subnet_ids = [for az in var.azs : data.aws_subnet.az[az].id]
  services = {
    catalogue       = 5001
    recommendations = 5002
    auth            = 5003
  }
}

# ---------------------------------------------------------------- security groups
resource "aws_security_group" "alb" {
  name   = "mini-netflix-s2-alb"
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

resource "aws_security_group" "app" {
  name   = "mini-netflix-s2-app"
  vpc_id = data.aws_vpc.default.id
  ingress {
    from_port       = 5001
    to_port         = 5003
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_security_group" "db" {
  name   = "mini-netflix-s2-db"
  vpc_id = data.aws_vpc.default.id
  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }
}

# ---------------------------------------------------------------- database (RDS)
resource "random_password" "db" {
  length  = 24
  special = false
}

resource "random_password" "token" {
  length  = 32
  special = false
}

resource "aws_db_subnet_group" "db" {
  name       = "mini-netflix-s2"
  subnet_ids = local.subnet_ids
}

resource "aws_db_instance" "db" {
  identifier              = "mini-netflix-s2"
  engine                  = "postgres"
  engine_version          = "16"
  instance_class          = var.db_instance_class
  allocated_storage       = 20
  storage_type            = "gp2"
  db_name                 = "minix"
  username                = "minix"
  password                = random_password.db.result
  db_subnet_group_name    = aws_db_subnet_group.db.name
  vpc_security_group_ids  = [aws_security_group.db.id]
  multi_az                = var.db_multi_az
  publicly_accessible     = false
  backup_retention_period = 0
  skip_final_snapshot     = true
  deletion_protection     = false
  apply_immediately       = true
}

# ---------------------------------------------------------------- load balancer
resource "aws_lb" "alb" {
  name               = "mini-netflix-s2"
  load_balancer_type = "application"
  subnets            = local.subnet_ids
  security_groups    = [aws_security_group.alb.id]
}

resource "aws_lb_target_group" "svc" {
  for_each             = local.services
  name                 = "mini-netflix-${each.key}"
  port                 = each.value
  protocol             = "HTTP"
  vpc_id               = data.aws_vpc.default.id
  deregistration_delay = 10
  # Every group judges an instance by the catalogue service (port 5001). Instance health then
  # means "can serve the home page", so stopping only the recommendations container (E4) tests
  # the circuit breaker instead of making the ASG replace every instance at once.
  health_check {
    path                = "/health"
    port                = "5001"
    interval            = 10
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 2
    matcher             = "200"
  }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.alb.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.svc["catalogue"].arn
  }
}

resource "aws_lb_listener_rule" "recommendations" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 10
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.svc["recommendations"].arn
  }
  condition {
    path_pattern { values = ["/recommendations/*"] }
  }
}

resource "aws_lb_listener_rule" "auth" {
  listener_arn = aws_lb_listener.http.arn
  priority     = 20
  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.svc["auth"].arn
  }
  condition {
    path_pattern { values = ["/login"] }
  }
}

# ---------------------------------------------------------------- compute (ASG)
resource "aws_launch_template" "app" {
  name_prefix            = "mini-netflix-s2-"
  image_id               = data.aws_ssm_parameter.al2023.value
  instance_type          = var.instance_type
  vpc_security_group_ids = [aws_security_group.app.id]
  iam_instance_profile { name = var.instance_profile }
  monitoring { enabled = true } # 1-minute CPU metrics so target tracking reacts within minutes
  metadata_options { http_tokens = "required" }
  user_data = base64encode(templatefile("${path.module}/user_data.sh", {
    region       = var.region
    registry     = split("/", var.image)[0]
    image        = var.image
    database_url = "postgresql://minix:${random_password.db.result}@${aws_db_instance.db.address}:5432/minix"
    token_secret = random_password.token.result
    breaker      = var.breaker
  }))
  tag_specifications {
    resource_type = "instance"
    tags          = { Name = "mini-netflix-s2", project = "mini-netflix", stage = "s2" }
  }
}

resource "aws_autoscaling_group" "app" {
  name                      = "mini-netflix-s2"
  vpc_zone_identifier       = local.subnet_ids
  min_size                  = var.min_size
  desired_capacity          = var.desired_capacity
  max_size                  = var.max_size
  health_check_type         = "ELB"
  health_check_grace_period = 120
  default_instance_warmup   = 60
  target_group_arns         = [for tg in aws_lb_target_group.svc : tg.arn]
  enabled_metrics           = ["GroupDesiredCapacity", "GroupInServiceInstances", "GroupPendingInstances", "GroupTerminatingInstances"]
  launch_template {
    id      = aws_launch_template.app.id
    version = aws_launch_template.app.latest_version
  }
  tag {
    key                 = "Name"
    value               = "mini-netflix-s2"
    propagate_at_launch = true
  }
}

resource "aws_autoscaling_policy" "cpu" {
  name                   = "cpu-target"
  autoscaling_group_name = aws_autoscaling_group.app.name
  policy_type            = "TargetTrackingScaling"
  target_tracking_configuration {
    predefined_metric_specification { predefined_metric_type = "ASGAverageCPUUtilization" }
    target_value = var.cpu_target
  }
}
