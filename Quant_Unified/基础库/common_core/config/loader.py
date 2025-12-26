"""
Configuration Loading Utilities
"""
import importlib.util
import os
from pathlib import Path
from typing import Type, TypeVar, Optional, Any, Dict

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


def load_config_from_module(
    module_path: str, 
    model: Type[T], 
    variable_name: str = "config"
) -> T:
    """
    Load configuration from a python module file and validate it against a Pydantic model.
    
    :param module_path: Path to the python file (e.g., 'config.py')
    :param model: Pydantic model class to validate against
    :param variable_name: The variable name in the module to load (default: 'config')
    :return: Instance of the Pydantic model
    """
    path = Path(module_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    spec = importlib.util.spec_from_file_location("dynamic_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec from {path}")
        
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    config_data = getattr(module, variable_name, None)
    if config_data is None:
        # Try to find a variable that matches the variable_name case-insensitive
        # or if variable_name is a dict of exports expected
        raise AttributeError(f"Variable '{variable_name}' not found in {module_path}")
        
    return model.model_validate(config_data)


def load_dict_from_module(module_path: str, variable_names: list[str]) -> Dict[str, Any]:
    """
    Load specific variables from a python module file.
    
    :param module_path: Path to the python file
    :param variable_names: List of variable names to retrieve
    :return: Dictionary of variable names to values
    """
    path = Path(module_path).resolve()
    if not path.exists():
        # Fallback: try relative to CWD
        path = Path.cwd() / module_path
        if not path.exists():
             raise FileNotFoundError(f"Config file not found: {module_path}")

    spec = importlib.util.spec_from_file_location("dynamic_config", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load spec from {path}")
        
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    result = {}
    for name in variable_names:
        if hasattr(module, name):
            result[name] = getattr(module, name)
            
    return result
