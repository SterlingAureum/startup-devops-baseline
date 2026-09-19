terraform {
  # This root must create the S3/KMS backend before that backend can be used.
  # It therefore remains on a separately protected local state in v0.12.1.
  # Moving this state to bootstrap/terraform.tfstate is a reviewed v0.12.2
  # migration action, not part of backend foundation creation.
}
