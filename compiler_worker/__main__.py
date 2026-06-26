from __future__ import annotations

import logging

from dotenv import load_dotenv

from compiler_worker.config import WorkerConfig
from compiler_worker.worker import WorkerLoop


def main() -> None:
    load_dotenv()
    config = WorkerConfig.from_env()
    logging.basicConfig(level=config.log_level)
    WorkerLoop(config).run()


if __name__ == "__main__":
    main()
