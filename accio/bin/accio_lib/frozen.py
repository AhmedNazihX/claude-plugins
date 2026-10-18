"""Read-only views of parsed JSON-like data, so callers can't change shared state by accident."""
import types


def freeze(value):
    """Return dicts as read-only mappings and lists as tuples, all the way down."""
    if isinstance(value, dict):
        return types.MappingProxyType({key: freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    return value
