data "aws_route53_zone" "public" {
  name         = var.hosted_zone_name
  private_zone = false
}

resource "aws_acm_certificate" "demo_api" {
  domain_name       = var.demo_hostname
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true

    precondition {
      condition     = endswith(var.demo_hostname, ".${var.hosted_zone_name}")
      error_message = "demo_hostname must be a subdomain of hosted_zone_name."
    }
  }

  tags = merge(var.tags, {
    Component = "tls-dns"
    Name      = var.demo_hostname
  })
}

resource "aws_route53_record" "certificate_validation" {
  for_each = {
    for option in aws_acm_certificate.demo_api.domain_validation_options :
    option.domain_name => {
      name   = option.resource_record_name
      record = option.resource_record_value
      type   = option.resource_record_type
    }
  }

  zone_id = data.aws_route53_zone.public.zone_id
  name    = each.value.name
  type    = each.value.type
  ttl     = 60
  records = [each.value.record]
}

resource "aws_acm_certificate_validation" "demo_api" {
  certificate_arn = aws_acm_certificate.demo_api.arn
  validation_record_fqdns = [
    for record in aws_route53_record.certificate_validation : record.fqdn
  ]
}
