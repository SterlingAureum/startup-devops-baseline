output "hosted_zone_id" {
  description = "ID of the existing public Route 53 hosted zone."
  value       = data.aws_route53_zone.public.zone_id
}

output "certificate_arn" {
  description = "ARN of the DNS-validated ACM certificate used by demo-api."
  value       = aws_acm_certificate_validation.demo_api.certificate_arn
}

output "demo_hostname" {
  description = "Public HTTPS hostname for demo-api."
  value       = var.demo_hostname
}
