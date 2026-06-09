"""
SCM Registry - Factory for creating SCM instances.

This module provides:
- Registration of SCM classes
- Factory function for creating SCM by experiment name
- Discovery of available SCMs

To add a new causal experiment:
1. Create SCM class inheriting from CausalSCM
2. Register it with @register_scm decorator or register_scm()
3. Create experiment config in experiments/<name>/game.json
"""

from typing import Type, Dict, Any, Optional, Callable
import importlib
import logging

from .scm_base import CausalSCM, BaseSCM, EnvironmentState

logger = logging.getLogger(__name__)


# Global registry mapping experiment names to SCM classes
SCM_REGISTRY: Dict[str, Type[CausalSCM]] = {}


def register_scm(
    name: str,
    scm_class: Optional[Type[CausalSCM]] = None
) -> Callable:
    """
    Register an SCM class for an experiment.

    Can be used as decorator or function:

    @register_scm("my_experiment")
    class MyExperimentSCM(CausalSCM):
        ...

    or:

    register_scm("my_experiment", MyExperimentSCM)

    Args:
        name: Experiment name
        scm_class: Optional SCM class (for function-style usage)

    Returns:
        Decorator or the registered class
    """
    def decorator(cls: Type[CausalSCM]) -> Type[CausalSCM]:
        SCM_REGISTRY[name] = cls
        logger.debug(f"Registered SCM '{cls.__name__}' for experiment '{name}'")
        return cls

    if scm_class is not None:
        return decorator(scm_class)

    return decorator


def get_scm_for_experiment(
    experiment_name: str,
    config: Optional[Dict[str, Any]] = None
) -> CausalSCM:
    """
    Factory function to create SCM for experiment.

    Args:
        experiment_name: Name of the experiment
        config: Experiment configuration

    Returns:
        Configured SCM instance

    Raises:
        ValueError: If experiment not found in registry
    """
    config = config or {}

    # Check registry
    scm_class = SCM_REGISTRY.get(experiment_name)

    if scm_class is None:
        # Try to auto-import
        scm_class = _try_auto_import(experiment_name)

    if scm_class is None:
        available = list(SCM_REGISTRY.keys())
        raise ValueError(
            f"Unknown experiment: {experiment_name}. "
            f"Available: {available}"
        )

    # Instantiate SCM with config
    return scm_class(config)


def _try_auto_import(experiment_name: str) -> Optional[Type[CausalSCM]]:
    """
    Try to auto-import SCM module.

    Looks for:
    - api.modules.environment.{experiment_name}
    - api.modules.environment.{experiment_name}_scm
    """
    module_names = [
        f"api.modules.environment.{experiment_name}",
        f"api.modules.environment.{experiment_name}_scm",
    ]

    for module_name in module_names:
        try:
            module = importlib.import_module(module_name)
            # Look for SCM class in module
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if (isinstance(attr, type) and
                    issubclass(attr, CausalSCM) and
                    attr is not CausalSCM and
                    attr is not BaseSCM):
                    # Found SCM class, register and return
                    register_scm(experiment_name, attr)
                    return attr
        except ImportError:
            continue

    return None


def list_experiments() -> Dict[str, str]:
    """
    List all registered experiments.

    Returns:
        Dict mapping experiment name to SCM class name
    """
    return {
        name: scm_class.__name__
        for name, scm_class in SCM_REGISTRY.items()
    }


def get_scm_info(experiment_name: str) -> Optional[Dict[str, Any]]:
    """
    Get information about an SCM.

    Args:
        experiment_name: Name of experiment

    Returns:
        Dict with SCM info or None if not found
    """
    scm_class = SCM_REGISTRY.get(experiment_name)

    if scm_class is None:
        return None

    return {
        'name': experiment_name,
        'class_name': scm_class.__name__,
        'module': scm_class.__module__,
        'doc': scm_class.__doc__,
    }


# ============================================================
# Import SCMs from separate files (auto-registers via decorator)
# ============================================================
# Each SCM is in its own file for easier collaboration.
# Import triggers the @register_scm decorator.

from . import default_scm  # noqa: F401 - registers "base"
from . import antenna_trap_scm  # noqa: F401 - registers "antenna_trap"
from . import deployment_zone_trap_scm  # noqa: F401 - registers "deployment_zone_trap"
from . import deployment_zone_shift_scm  # noqa: F401 - registers "deployment_zone_shift"

# Register the categorical variant using the same SCM (only action_space differs)
register_scm("deployment_zone_trap_categorical", deployment_zone_trap_scm.DeploymentZoneTrapSCM)

# Register no-selection-bias variants (same SCM, only hide_failed_drones differs in game.json)
register_scm("antenna_trap_no_selection_bias", antenna_trap_scm.AntennaTrapSCM)
register_scm("deployment_zone_trap_no_selection_bias", deployment_zone_trap_scm.DeploymentZoneTrapSCM)
