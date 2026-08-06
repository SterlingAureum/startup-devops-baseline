terraform {
  # The ephemeral test environment intentionally keeps an independent local
  # state in this directory for the sequential v0.9 portfolio validation.
  #
  # An encrypted S3 backend with state locking will be introduced before the
  # environment is used by multiple operators or automated apply workflows.
}
