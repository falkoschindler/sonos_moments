import importlib.metadata

try:
    __version__: str = importlib.metadata.version('sonos_moments')
except importlib.metadata.PackageNotFoundError:
    __version__ = 'unknown'
