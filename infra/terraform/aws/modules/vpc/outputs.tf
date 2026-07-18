output "vpc_id" {
  description = "ID of the VPC."
  value       = aws_vpc.this.id
}

output "vpc_cidr" {
  description = "IPv4 CIDR block of the VPC."
  value       = aws_vpc.this.cidr_block
}

output "public_subnet_ids" {
  description = "Public subnet IDs ordered by availability_zones."
  value       = [for az in var.availability_zones : aws_subnet.public[az].id]
}

output "private_subnet_ids" {
  description = "Private subnet IDs ordered by availability_zones."
  value       = [for az in var.availability_zones : aws_subnet.private[az].id]
}

output "public_route_table_id" {
  description = "ID of the shared public route table."
  value       = aws_route_table.public.id
}

output "private_route_table_ids" {
  description = "Private route table IDs ordered by availability_zones."
  value       = [for az in var.availability_zones : aws_route_table.private[az].id]
}

output "nat_gateway_ids" {
  description = "IDs of NAT Gateways created for private subnet egress."
  value       = [for key in local.nat_gateway_keys : aws_nat_gateway.this[key].id]
}
