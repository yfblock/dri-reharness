"""Backend code generators (plan Milestone 6).

Each backend defines a prompt template (prompts/<name>.md) and delegates
code generation to the LLM bridge.  The bind (make_bind) and registry
infrastructure remain rule-based.
"""
from .registry import (  # noqa: F401
    register, get_backend, list_backends, backend_names,
)
