import uvicorn

from .logging_config import configure_logging
from .tracing import configure_tracing


def main() -> None:
    configure_logging()
    configure_tracing()
    uvicorn.run(
        "src.main:app",
        host="0.0.0.0",
        port=8080,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
