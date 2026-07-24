# AWS FIS Spot interruption module

This module creates the controlled fault-injection infrastructure used by the
Karpenter Spot replacement drill:

- an AWS FIS experiment role with source-account and source-experiment trust
  conditions;
- a least-privilege inline policy for describing instances and sending Spot
  interruption notices;
- one experiment template using
  `aws:ec2:send-spot-instance-interruptions`;
- a tag-scoped `aws:ec2:spot-instance` target with `COUNT(1)`;
- a fixed two-minute interruption notice.

The target tag must be unique to the dedicated test `EC2NodeClass`. Do not
reuse that tag on normal application nodes.
