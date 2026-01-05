#!/usr/bin/env python3
"""
=============================================================================
Configuration Loader
=============================================================================
Handles loading and merging YAML configuration files.
"""

import os
import yaml
from pathlib import Path
from typing import Any, Dict, Optional


class ConfigLoader:
    """Load and manage framework configuration."""
    
    def __init__(self, config_path: str = "config/framework.yaml"):
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent.parent
        self._config: Dict[str, Any] = {}
    
    def load(self) -> Dict[str, Any]:
        """Load the main configuration file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        
        with open(self.config_path, 'r') as f:
            self._config = yaml.safe_load(f) or {}
        
        # Expand environment variables
        self._expand_env_vars(self._config)
        
        return self._config
    
    def load_profile(self, profile_name: str) -> Dict[str, Any]:
        """Load an instance profile and merge with main config."""
        profile_path = self.base_dir / "config" / "instance-profiles" / f"{profile_name}.yaml"
        
        if not profile_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_name}")
        
        with open(profile_path, 'r') as f:
            profile = yaml.safe_load(f) or {}
        
        # Merge profile with main config
        merged = self._deep_merge(self._config.copy(), profile)
        
        return merged
    
    def _expand_env_vars(self, obj: Any) -> None:
        """Recursively expand environment variables in config values."""
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    obj[key] = self._expand_string(value)
                elif isinstance(value, (dict, list)):
                    self._expand_env_vars(value)
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                if isinstance(item, str):
                    obj[i] = self._expand_string(item)
                elif isinstance(item, (dict, list)):
                    self._expand_env_vars(item)
    
    def _expand_string(self, value: str) -> str:
        """Expand environment variables in a string."""
        # Handle ${VAR} syntax
        import re
        pattern = r'\$\{([^}]+)\}'
        
        def replace(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        
        return re.sub(pattern, replace, value)
    
    def _deep_merge(self, base: Dict, override: Dict) -> Dict:
        """Deep merge two dictionaries."""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        
        return result
    
    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get a configuration value using dot notation.
        
        Example:
            config.get('aws.ec2.controller.instance_type')
        """
        keys = key_path.split('.')
        value = self._config
        
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        
        return value
    
    @property
    def config(self) -> Dict[str, Any]:
        """Get the loaded configuration."""
        return self._config


def merge_cli_args(config: Dict[str, Any], args) -> Dict[str, Any]:
    """Merge CLI arguments into configuration."""
    merged = config.copy()
    
    # Map CLI args to config paths
    mappings = {
        'workers': ['workers', 'count'],
        'results_dir': ['results', 'local_dir'],
    }
    
    for arg_name, config_path in mappings.items():
        value = getattr(args, arg_name, None)
        if value is not None:
            # Navigate to the right location and set value
            current = merged
            for key in config_path[:-1]:
                if key not in current:
                    current[key] = {}
                current = current[key]
            current[config_path[-1]] = value
    
    return merged
