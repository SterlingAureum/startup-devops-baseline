import os


def runtime_identity() -> dict[str, str]:
    """Return the canonical release identity shared by logs and traces."""

    service_name = os.getenv("APP_NAME", "demo-api")
    service_version = os.getenv("APP_VERSION", "0.1.0")
    return {
        "service.name": service_name,
        "service.version": service_version,
        "deployment.environment.name": os.getenv("APP_ENV", "local"),
        "platform.release.id": os.getenv(
            "PLATFORM_RELEASE_ID",
            f"{service_name}-local-{service_version}",
        ),
        "platform.source.commit": os.getenv(
            "PLATFORM_SOURCE_COMMIT",
            "local-unavailable",
        ),
        "container.image.digest": os.getenv(
            "CONTAINER_IMAGE_DIGEST",
            "local-unpinned",
        ),
    }
