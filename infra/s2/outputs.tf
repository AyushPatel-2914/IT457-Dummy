output "url" { value = "http://${aws_lb.alb.dns_name}" }
output "asg_name" { value = aws_autoscaling_group.app.name }
output "catalogue_target_group" { value = aws_lb_target_group.svc["catalogue"].name }
output "azs" { value = var.azs }
output "fis_templates" {
  value = var.enable_fis ? {
    terminate_one = aws_fis_experiment_template.terminate_one[0].id
    az_outage     = aws_fis_experiment_template.az_outage[0].id
    cpu_stress    = aws_fis_experiment_template.cpu_stress[0].id
  } : {}
}
