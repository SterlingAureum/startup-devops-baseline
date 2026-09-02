# Explicit, reviewed qualification profile; NOT an auto.tfvars file.
# Not consumed by existing apply-aws-test.sh. No live entrypoint in .8.2.0.
# Four nodes are a conservative starting point, not a capacity guarantee.
eks_node_min_size     = 4
eks_node_desired_size = 4
eks_node_max_size     = 4
