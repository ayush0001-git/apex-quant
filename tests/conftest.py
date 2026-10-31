# tests/conftest.py
"""Pytest setup and configuration for Apex Quant-Terminal."""
import os

# Prevent joblib/loky on Windows from launching wmic subprocess during tests
os.environ["LOKY_MAX_CPU_COUNT"] = "2"

