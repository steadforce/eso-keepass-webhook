import logging
import sys
from collections.abc import Callable

import uvicorn

from .app import create_app
from .config import Config, ConfigError, SecretFile
from .store import Store

log = logging.getLogger("eso_keepass_webhook")


def main() -> None:
    try:
        config = Config.from_env()
        auth_token: Callable[[], str] = (
            SecretFile(config.auth_token_file).get
            if config.auth_token_file
            else lambda: config.auth_token
        )
    except (ConfigError, OSError, ValueError) as e:
        sys.exit(f"invalid configuration: {e}")

    logging.basicConfig(
        level=config.log_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        store = Store(
            config.database,
            password=config.password,
            password_file=config.password_file,
            keyfile=config.keyfile,
        )
    except Exception as e:
        log.error("cannot open %s: %s", config.database, e)
        sys.exit(1)
    store.watch(config.reload_interval)

    uvicorn.run(
        create_app(store, auth_token),
        host="0.0.0.0",  # noqa: S104 - runs in a container
        port=config.port,
        log_config=None,
        access_log=False,
        server_header=False,
    )


if __name__ == "__main__":
    main()
