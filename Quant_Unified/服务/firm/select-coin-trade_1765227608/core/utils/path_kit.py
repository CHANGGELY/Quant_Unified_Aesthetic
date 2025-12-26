"""
Quant Unified 量化交易系统
path_kit.py
"""
import os
from pathlib import Path

try:
    from common_core.utils.path_kit import (
        get_folder_by_root as _get_folder_by_root,
        get_folder_path as _get_folder_path_common,
        get_file_path as _get_file_path_common,
        PROJECT_ROOT as _PROJECT_ROOT,
    )

    PROJECT_ROOT = _PROJECT_ROOT

    def get_folder_by_root(root, *paths, auto_create=True) -> str:
        return _get_folder_by_root(root, *paths, auto_create=auto_create)

    def get_folder_path(*paths, auto_create=True, path_type=False) -> str | Path:
        _p = _get_folder_path_common(*paths, auto_create=auto_create, as_path_type=path_type)
        return _p

    def get_file_path(*paths, auto_create=True, as_path_type=False) -> str | Path:
        return _get_file_path_common(*paths, auto_create=auto_create, as_path_type=as_path_type)

except Exception:
    # Fallback to local implementation if common_core is not available
    PROJECT_ROOT = os.path.abspath(os.path.join(__file__, os.path.pardir, os.path.pardir, os.path.pardir, os.path.pardir))

    def get_folder_by_root(root, *paths, auto_create=True) -> str:
        _full_path = os.path.join(root, *paths)
        if auto_create and (not os.path.exists(_full_path)):
            try:
                os.makedirs(_full_path)
            except FileExistsError:
                pass
        return str(_full_path)

    def get_folder_path(*paths, auto_create=True, path_type=False) -> str | Path:
        _p = get_folder_by_root(PROJECT_ROOT, *paths, auto_create=auto_create)
        if path_type:
            return Path(_p)
        return _p

    def get_file_path(*paths, auto_create=True, as_path_type=False) -> str | Path:
        parent = get_folder_path(*paths[:-1], auto_create=auto_create, path_type=True)
        _p_119 = parent / paths[-1]
        if as_path_type:
            return _p_119
        return str(_p_119)
