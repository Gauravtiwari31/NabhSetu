"""Operator errors: a wrong configuration, not a defect in the code.

These live in their own dependency-free module so the CLI can catch them
without importing the collection or pipeline stacks (and their pandas/numpy
cost) just to build its argument parser.

The distinction matters to whoever is running the thing. A traceback says
"this tool is broken, file a bug". These say "the run could not proceed, and
here is the setting that stopped it" -- which is a different action.
"""
from __future__ import annotations


class OperatorError(RuntimeError):
    """Base class for failures an operator can fix by changing configuration."""
