# VPC module

This module creates the v0.4.1 AWS network baseline for the future EKS cluster.

## Resources

- one VPC with DNS support and DNS hostnames enabled;
- public and private subnets across at least two Availability Zones;
- one Internet Gateway;
- one shared public route table;
- one private route table per Availability Zone;
- NAT Gateway egress for private subnets;
- EKS and AWS Load Balancer Controller subnet discovery tags.

The development environment defaults to a single shared NAT Gateway to reduce
cost. Setting `single_nat_gateway = false` creates one NAT Gateway per
Availability Zone for higher availability.

Worker nodes will later use the private subnets. Internet-facing load balancers
will use the public subnets.
