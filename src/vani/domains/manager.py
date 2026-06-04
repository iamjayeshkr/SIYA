"""
src/vani/domains/manager.py — Dynamic domain manager and discovery engine
"""

from __future__ import annotations
import importlib
import inspect
import logging
from pathlib import Path
from typing import Dict
from vani.domains.base import DomainModule
from vani.reasoning.registry import register_tool

logger = logging.getLogger("vani.domains.manager")


class DomainManager:
    """
    Scans the domains directory, loads modules, registers domain tools 
    and prompt modifications dynamically.
    """

    _domains: Dict[str, DomainModule] = {}

    @classmethod
    def load_domains(cls) -> None:
        """Scan the current package for subclasses of DomainModule and load them."""
        cls._domains.clear()
        domains_dir = Path(__file__).parent

        for file in domains_dir.glob("*.py"):
            name = file.stem
            if name in ("__init__", "base", "manager"):
                continue

            try:
                module_path = f"vani.domains.{name}"
                module = importlib.import_module(module_path)

                # Scan for DomainModule subclasses
                for member_name, member in inspect.getmembers(module):
                    if (
                        inspect.isclass(member)
                        and issubclass(member, DomainModule)
                        and member is not DomainModule
                    ):
                        inst = member()
                        cls._domains[inst.name] = inst
                        logger.info(f"Loaded Domain Module: {inst.name}")

                        # Register tools dynamically
                        for tool_name, (fn, desc) in inst.get_tools().items():
                            try:
                                register_tool(tool_name, fn, desc)
                            except Exception as e:
                                logger.warning(
                                    f"Failed to register tool {tool_name} from domain {inst.name}: {e}"
                                )

            except Exception as e:
                logger.error(f"Failed to load domain file {file}: {e}")

    @classmethod
    def get_domains(cls) -> Dict[str, DomainModule]:
        return cls._domains

    @classmethod
    def get_domain(cls, name: str) -> DomainModule | None:
        return cls._domains.get(name)

    @classmethod
    def get_domain_descriptions_prompt(cls) -> str:
        """Compile a combined description of active domains to guide reasoning."""
        if not cls._domains:
            return ""
        prompt = "\nActive Specialized Domain Modules available:\n"
        for name, dom in cls._domains.items():
            prompt += f"- {name.upper()}: {dom.description}\n"
        return prompt
