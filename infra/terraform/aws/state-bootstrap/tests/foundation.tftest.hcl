mock_provider "aws" {
  mock_data "aws_iam_policy_document" {
    defaults = { json = "{\"Version\":\"2012-10-17\",\"Statement\":[]}" }
  }
  mock_data "aws_partition" {
    defaults = { partition = "aws", dns_suffix = "amazonaws.com" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
}

variables {
  state_bucket_name = "baseline-fixture-state"
}

run "fresh_sse_s3" {
  command = plan
  variables {
    state_key_overrides = { dev = "team-a/dev/state" }
  }
  assert {
    condition = (
      length(aws_kms_key.state) == 0 && length(aws_kms_alias.state) == 0 &&
      !contains(keys(output.backend_configuration.dev), "kms_key_id") &&
      output.backend_configuration.dev.key == "team-a/dev/state" &&
      one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256"
    )
    error_message = "Expected custom state path with SSE-S3 and no KMS key."
  }
}

run "existing_key" {
  command = plan
  variables {
    state_encryption     = "existing-kms"
    existing_kms_key_arn = "arn:aws:kms:us-east-1:123456789012:key/12345678-1234-1234-1234-123456789012"
  }
  assert {
    condition = (
      length(aws_kms_key.state) == 0 && length(aws_kms_alias.state) == 0 &&
      output.backend_configuration.dev.kms_key_id == var.existing_kms_key_arn &&
      one(one(aws_s3_bucket_server_side_encryption_configuration.state.rule).apply_server_side_encryption_by_default).kms_master_key_id == var.existing_kms_key_arn
    )
    error_message = "Expected the supplied key for the backend and bucket."
  }
}

run "managed_key" {
  command = plan
  variables {
    state_encryption = "managed-kms"
  }
  assert {
    condition = (
      length(aws_kms_key.state) == 1 && length(aws_kms_alias.state) == 1 &&
      contains(keys(output.backend_configuration.dev), "kms_key_id") &&
      output.backend_configuration.dev.key == "environments/dev/terraform.tfstate"
    )
    error_message = "Existing inputs must retain the managed KMS key and state paths."
  }
}

run "overlapping_lock" {
  command = plan
  variables {
    state_key_overrides = { dev = "environments/test/terraform.tfstate.tflock" }
  }
  expect_failures = [aws_s3_bucket.state]
}
