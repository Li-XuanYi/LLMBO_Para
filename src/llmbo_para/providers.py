"""Explicit research-group extension imports, executed only after preflight."""

import importlib


def load_factory(reference: str):
    if not isinstance(reference, str) or reference.count(":") != 1:
        raise ValueError("factory reference must be module:callable")
    module_name, name = reference.split(":")
    factory = getattr(importlib.import_module(module_name), name)
    if not callable(factory):
        raise ValueError("configured factory is not callable")
    return factory
