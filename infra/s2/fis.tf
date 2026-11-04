# Optional AWS Fault Injection Service templates: the managed, auditable version of chaos_monkey.py.
# Start one with: aws fis start-experiment --experiment-template-id <id>
resource "aws_iam_role" "fis" {
  count = var.enable_fis ? 1 : 0
  name  = "mini-netflix-fis"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "fis.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
}

resource "aws_iam_role_policy_attachment" "fis" {
  for_each = var.enable_fis ? toset([
    "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorEC2Access",
    "arn:aws:iam::aws:policy/service-role/AWSFaultInjectionSimulatorSSMAccess",
  ]) : toset([])
  role       = aws_iam_role.fis[0].name
  policy_arn = each.value
}

# Stop condition: abort any experiment if the ALB returns many 5xx errors (limits blast radius).
resource "aws_cloudwatch_metric_alarm" "alb_5xx" {
  count               = var.enable_fis ? 1 : 0
  alarm_name          = "mini-netflix-s2-5xx"
  namespace           = "AWS/ApplicationELB"
  metric_name         = "HTTPCode_ELB_5XX_Count"
  dimensions          = { LoadBalancer = aws_lb.alb.arn_suffix }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 500
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
}

resource "aws_fis_experiment_template" "terminate_one" {
  count       = var.enable_fis ? 1 : 0
  description = "E1 (FIS): terminate one random s2 instance"
  role_arn    = aws_iam_role.fis[0].arn
  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.alb_5xx[0].arn
  }
  action {
    name      = "terminate-one"
    action_id = "aws:ec2:terminate-instances"
    target {
      key   = "Instances"
      value = "s2-instances"
    }
  }
  target {
    name           = "s2-instances"
    resource_type  = "aws:ec2:instance"
    selection_mode = "COUNT(1)"
    resource_tag {
      key   = "stage"
      value = "s2"
    }
    filter {
      path   = "State.Name"
      values = ["running"]
    }
  }
}

resource "aws_fis_experiment_template" "az_outage" {
  count       = var.enable_fis ? 1 : 0
  description = "E2 (FIS): terminate every s2 instance in the first AZ"
  role_arn    = aws_iam_role.fis[0].arn
  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.alb_5xx[0].arn
  }
  action {
    name      = "terminate-az"
    action_id = "aws:ec2:terminate-instances"
    target {
      key   = "Instances"
      value = "s2-az"
    }
  }
  target {
    name           = "s2-az"
    resource_type  = "aws:ec2:instance"
    selection_mode = "ALL"
    resource_tag {
      key   = "stage"
      value = "s2"
    }
    filter {
      path   = "State.Name"
      values = ["running"]
    }
    filter {
      path   = "Placement.AvailabilityZone"
      values = [var.azs[0]]
    }
  }
}

resource "aws_fis_experiment_template" "cpu_stress" {
  count       = var.enable_fis ? 1 : 0
  description = "E5 (FIS): 5 minutes of CPU stress on every s2 instance"
  role_arn    = aws_iam_role.fis[0].arn
  stop_condition {
    source = "aws:cloudwatch:alarm"
    value  = aws_cloudwatch_metric_alarm.alb_5xx[0].arn
  }
  action {
    name      = "cpu-stress"
    action_id = "aws:ssm:send-command"
    parameter {
      key   = "documentArn"
      value = "arn:aws:ssm:${var.region}::document/AWSFIS-Run-CPU-Stress"
    }
    parameter {
      key   = "documentParameters"
      value = jsonencode({ DurationSeconds = "300", InstallDependencies = "True" })
    }
    parameter {
      key   = "duration"
      value = "PT6M"
    }
    target {
      key   = "Instances"
      value = "s2-all"
    }
  }
  target {
    name           = "s2-all"
    resource_type  = "aws:ec2:instance"
    selection_mode = "ALL"
    resource_tag {
      key   = "stage"
      value = "s2"
    }
    filter {
      path   = "State.Name"
      values = ["running"]
    }
  }
}
