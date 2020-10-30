from collections.abc import MutableMapping
from pathlib import Path
import re
from requests.models import PreparedRequest
import yaml

_url_pattern = re.compile(r"^https?://")
# A validator must be defined for a key with this type to be validated.
_validators = {
    "string": lambda value: True,
    "url": lambda value: _url_pattern.match(PreparedRequest().prepare_url(value, None).url),
    "number": lambda value: str(int(value)) == value,
}

class Config(MutableMapping):
    def __init__(self, path='config.yml'):
        self.path = Path(path)
        with self.path.open('r') as config_file:
            self.config = yaml.safe_load(config_file)
        with Path("config_types.yml").open('r') as config_types_file:
            self.config_types = yaml.safe_load(config_types_file)

    def __getitem__(self, key):
        return self.config[key]

    def __setitem__(self, key, value):
        self.config[key] = value

    def __delitem__(self, key):
        del self.config[key]

    def __iter__(self):
        return iter(self.config)

    def __len__(self):
        return len(self.config)

    def validate(self, key, value):
        if key not in self.config_types:
            raise TypeError(f"No type known for {key}")
        if self.config_types[key] not in _validators:
            raise TypeError(f"No validator known for {key}'s type ({self.config_types[key]})")

        return _validators[self.config_types[key]](value)

    def sync(self):
        with self.path.open('w') as config_file:
            yaml.dump(self.config, config_file)

class ServerConfig(MutableMapping):
    def __init__(self, config, server=None):
        self.config = config
        if server is None:
            self.server_config = self.config
        else:
            self.server_config = self.config.setdefault(server, {})

    def __getitem__(self, key):
        return self.server_config.get(key, self.config[key])

    def __setitem__(self, key, value):
        self.server_config[key] = value

    def __delitem__(self, key):
        del self.server_config[key]

    def __iter__(self):
        return iter(self.config.keys() | self.server_config.keys())

    def __len__(self):
        return len(self.config.keys() | self.server_config.keys())

    def sync(self):
        self.config.sync()
