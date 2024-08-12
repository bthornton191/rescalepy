import json
from pathlib import Path
import keyring

CONFIG_FILE = Path.home() / '.rescalepy'
KEYRING_SERVICE = 'test_rescale'
KEYRING_USERNAME = 'api'


def set_config(**kwargs):
    config = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    config.update(kwargs)
    json.dump(config, CONFIG_FILE.open('w'))


def get_config(key: str):
    config = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    return config.get(key)


def set_api_key(api_key: str):
    keyring.set_password(KEYRING_SERVICE, KEYRING_USERNAME, api_key)


def unset_api_key():
    keyring.delete_password(KEYRING_SERVICE, KEYRING_USERNAME)


def get_api_key() -> str:
    api_key = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)

    return api_key
