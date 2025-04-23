from dotenv import load_dotenv
import os
from typing import Optional

def init_env() -> None:
    load_dotenv()

def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    return os.getenv(key, default)

def get_config_path() -> str:
    config_path = os.getenv('CONFIG_FILE_PATH')
    if config_path is None:
        raise ValueError("CONFIG_FILE_PATH environment variable is not defined")
    return config_path

init_env()

