"""PyInstaller hook: bundle the Playwright driver (node.exe + package/) and package data."""
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("playwright", include_py_files=False)
datas += collect_data_files("playwright", subdir="driver")
