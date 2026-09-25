terraform {
  backend "s3" {}

  # This root must create the S3/KMS backend before that backend can be used.
  # v0.12.2.1 only declares this partial backend and prepares a separately
  # reviewed command plan. The state remains local until v0.12.2.2 executes
  # the exact approved terraform init -migrate-state boundary.
}
