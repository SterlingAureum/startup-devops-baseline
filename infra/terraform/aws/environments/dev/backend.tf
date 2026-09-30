terraform {
  backend "s3" {}

  # Backend values are materialized only in an owner-readable private file
  # generated from state-bootstrap output. This root is initialized only from
  # a reviewed private staged source after remote state and lock absence proof.
  # Clean-room creation uses terraform init -reconfigure, never -migrate-state.
}
