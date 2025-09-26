#!/usr/bin/env python3
"""
Nexus3 Backup and Restore Tool
Main entry point for the application
"""

import sys
import os
from pathlib import Path

# Add the scripts directory to the Python path
current_dir = Path(__file__).parent
scripts_dir = current_dir / "scripts"
sys.path.insert(0, str(scripts_dir))

# Import the CLI application
from commands import app

if __name__ == "__main__":
    app()
