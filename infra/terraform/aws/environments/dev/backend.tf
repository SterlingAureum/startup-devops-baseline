terraform {
  # The development environment intentionally uses Terraform's local backend
  # during the initial v0.4 skeleton phase.
  #
  # An encrypted S3 backend with state locking will be introduced before the
  # environment is used by multiple operators or automated apply workflows.
}
