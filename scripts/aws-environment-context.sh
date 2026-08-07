#!/usr/bin/env bash

# Source this file after ROOT_DIR is defined. It maps the repository's public
# aws-* environment identity to the corresponding Terraform and GitOps names.
configure_aws_environment_context() {
  if [[ -z "${ROOT_DIR:-}" ]]; then
    echo "ROOT_DIR must be set before sourcing aws-environment-context.sh." >&2
    return 1
  fi

  case "${AWS_ENVIRONMENT:-}" in
    aws-dev)
      ENVIRONMENT_SHORT="dev"
      CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-dev}"
      ROOT_APPLICATION="${ROOT_APPLICATION:-startup-devops-aws-dev-root}"
      DEMO_APPLICATION="${DEMO_APPLICATION:-demo-api-aws-dev}"
      DEMO_HOSTNAME="${DEMO_HOSTNAME:-demo.dev.aureumstack.com}"
      EKS_CLUSTER_LOG_RETENTION_DAYS="${EKS_CLUSTER_LOG_RETENTION_DAYS:-14}"
      ;;
    aws-test)
      ENVIRONMENT_SHORT="test"
      CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-test}"
      ROOT_APPLICATION="${ROOT_APPLICATION:-startup-devops-aws-test-root}"
      DEMO_APPLICATION="${DEMO_APPLICATION:-demo-api-aws-test}"
      DEMO_HOSTNAME="${DEMO_HOSTNAME:-demo.test.aureumstack.com}"
      EKS_CLUSTER_LOG_RETENTION_DAYS="${EKS_CLUSTER_LOG_RETENTION_DAYS:-30}"
      ;;
    aws-prod)
      ENVIRONMENT_SHORT="prod"
      CLUSTER_NAME="${CLUSTER_NAME:-startup-devops-baseline-prod}"
      ROOT_APPLICATION="${ROOT_APPLICATION:-startup-devops-aws-prod-root}"
      DEMO_APPLICATION="${DEMO_APPLICATION:-demo-api-aws-prod}"
      DEMO_HOSTNAME="${DEMO_HOSTNAME:-demo.prod.aureumstack.com}"
      EKS_CLUSTER_LOG_RETENTION_DAYS="${EKS_CLUSTER_LOG_RETENTION_DAYS:-90}"
      ;;
    *)
      echo "AWS_ENVIRONMENT must be aws-dev, aws-test, or aws-prod." >&2
      return 1
      ;;
  esac

  TF_DIR="${TF_DIR:-${ROOT_DIR}/infra/terraform/aws/environments/${ENVIRONMENT_SHORT}}"
  SOURCE_FILE="${SOURCE_FILE:-${ROOT_DIR}/clusters/aws/overlays/${ENVIRONMENT_SHORT}/root-app.yaml}"
  AWS_REGION="${AWS_REGION:-us-east-1}"
  PROJECT_NAME="${PROJECT_NAME:-startup-devops-baseline}"
  HOSTED_ZONE_NAME="${HOSTED_ZONE_NAME:-aureumstack.com}"

  export AWS_REGION CLUSTER_NAME DEMO_APPLICATION DEMO_HOSTNAME
  export ENVIRONMENT_SHORT EKS_CLUSTER_LOG_RETENTION_DAYS HOSTED_ZONE_NAME
  export PROJECT_NAME ROOT_APPLICATION SOURCE_FILE TF_DIR
}
