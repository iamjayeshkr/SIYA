"""
src/vani/domains/base.py — Abstract base class for Vanni Domain Modules
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Callable


class DomainModule(ABC):
    """
    Base class representing a specialized domain.
    Domains register tools and reasoning prompts with Vanni's core OS dynamically.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The canonical name of the domain module (e.g. 'software_engineering')."""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """A brief description of what this domain handles, injected into agent prompts."""
        pass

    @abstractmethod
    def get_tools(self) -> dict[str, tuple[Callable, str]]:
        """
        Return a dictionary of tools defined by this domain.
        Mapping: tool_name -> (callable_fn, tool_description_str)
        """
        pass

    @abstractmethod
    def get_prompts(self) -> dict[str, str]:
        """
        Return system prompt modifications or templates owned by this domain.
        """
        pass
