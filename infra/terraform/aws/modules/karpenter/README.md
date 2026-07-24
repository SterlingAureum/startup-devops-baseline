# Karpenter AWS Foundation Module

This module creates the AWS-side foundation required before the Karpenter
controller and its Kubernetes custom resources are installed.

It manages:

- the Karpenter controller IRSA role
- six scoped controller IAM policies aligned with Karpenter 1.14
- the IAM role used by Karpenter-provisioned nodes
- the EKS `EC2_LINUX` access entry for that node role
- an encrypted SQS interruption queue
- EventBridge interruption rules and queue targets
- the discovery tag on the EKS cluster security group

Private subnet discovery tags remain owned by the VPC module because that
module owns the subnets.

This module does not install Karpenter in Kubernetes and does not create an
`EC2NodeClass`, `NodePool`, or `NodeClaim`. Those resources are introduced by
the following GitOps increment.
