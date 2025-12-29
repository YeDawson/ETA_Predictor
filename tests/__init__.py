"""
pytest configuration for the test suite.
Adds the backend directory to sys.path so backend modules can be imported
without installing the package.
"""
import sys
import os

# Make `import graph_manager`, `import routing`, etc. work from any test file
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
