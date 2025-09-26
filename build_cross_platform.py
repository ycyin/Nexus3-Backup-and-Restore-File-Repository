#!/usr/bin/env python3
"""
Cross-platform build script for Nexus3 Tool
Supports building for multiple platforms from a single machine
"""

import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path
import argparse

# Supported platforms
PLATFORMS = {
    'windows': {
        'pyinstaller_args': ['--onefile', '--console'],
        'executable_name': 'nexus3-tool.exe',
        'icon': None
    },
    'linux': {
        'pyinstaller_args': ['--onefile', '--console'],
        'executable_name': 'nexus3-tool',
        'icon': None
    },
    'macos': {
        'pyinstaller_args': ['--onefile', '--console'],
        'executable_name': 'nexus3-tool',
        'icon': None
    }
}

def run_command(cmd, description, cwd=None):
    """Run a command and handle errors"""
    print(f"\n🔧 {description}...")
    print(f"Command: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=cwd)
        print(f"✅ {description} completed successfully")
        if result.stdout.strip():
            print(f"Output: {result.stdout.strip()}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed")
        print(f"Error: {e.stderr.strip()}")
        return False

def clean_build_dirs():
    """Clean previous build directories"""
    print("🧹 Cleaning previous builds...")
    build_dirs = ["build", "dist", "__pycache__"]
    for dir_name in build_dirs:
        if Path(dir_name).exists():
            shutil.rmtree(dir_name)
            print(f"  Removed {dir_name}/")
    
    # Clean Python cache files
    for root, dirs, files in os.walk("."):
        for dir_name in dirs[:]:
            if dir_name == "__pycache__":
                shutil.rmtree(Path(root) / dir_name)
                dirs.remove(dir_name)

def install_dependencies():
    """Install required dependencies"""
    return run_command([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], 
                      "Installing dependencies")

def create_spec_file(target_platform):
    """Create platform-specific spec file"""
    platform_config = PLATFORMS[target_platform]
    
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-
# Auto-generated spec file for {target_platform}

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('scripts', 'scripts'),
    ],
    hiddenimports=[
        'aiohttp',
        'typer',
        'tabulate',
        'tqdm',
        'xml.etree.ElementTree',
        'asyncio',
        'pathlib',
        'urllib.parse',
    ],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='{platform_config["executable_name"]}',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon={platform_config["icon"]},
)
'''
    
    spec_file = f"nexus3-tool-{target_platform}.spec"
    with open(spec_file, 'w') as f:
        f.write(spec_content)
    
    return spec_file

def build_for_platform(target_platform):
    """Build executable for specific platform"""
    if target_platform not in PLATFORMS:
        print(f"❌ Unsupported platform: {target_platform}")
        return False
    
    print(f"\n🚀 Building for {target_platform}...")
    
    # Create platform-specific spec file
    spec_file = create_spec_file(target_platform)
    
    # Build with PyInstaller
    cmd = [sys.executable, "-m", "PyInstaller", spec_file, "--clean", "--noconfirm"]
    
    if run_command(cmd, f"Building {target_platform} executable"):
        platform_config = PLATFORMS[target_platform]
        exe_path = Path("dist") / platform_config["executable_name"]
        
        if exe_path.exists():
            size_mb = exe_path.stat().st_size / (1024 * 1024)
            print(f"📦 {target_platform} executable created: {exe_path}")
            print(f"📏 File size: {size_mb:.1f} MB")
            
            # Create platform-specific directory
            platform_dir = Path("dist") / target_platform
            platform_dir.mkdir(exist_ok=True)
            
            # Move executable to platform directory
            target_path = platform_dir / platform_config["executable_name"]
            shutil.move(exe_path, target_path)
            
            # Make executable on Unix systems
            if target_platform in ['linux', 'macos']:
                os.chmod(target_path, 0o755)
                print("🔧 Made file executable")
            
            print(f"✅ {target_platform} build completed: {target_path}")
            return True
        else:
            print(f"❌ {target_platform} executable not found after build")
            return False
    else:
        return False

def build_all_platforms():
    """Build for all supported platforms"""
    success_count = 0
    total_count = len(PLATFORMS)
    
    for platform_name in PLATFORMS:
        if build_for_platform(platform_name):
            success_count += 1
        
        # Clean up spec file
        spec_file = f"nexus3-tool-{platform_name}.spec"
        if Path(spec_file).exists():
            os.remove(spec_file)
    
    print(f"\n📊 Build Summary: {success_count}/{total_count} platforms built successfully")
    
    if success_count > 0:
        print("\n📦 Built executables:")
        for platform_name in PLATFORMS:
            platform_config = PLATFORMS[platform_name]
            exe_path = Path("dist") / platform_name / platform_config["executable_name"]
            if exe_path.exists():
                size_mb = exe_path.stat().st_size / (1024 * 1024)
                print(f"  {platform_name}: {exe_path} ({size_mb:.1f} MB)")

def detect_current_platform():
    """Detect the current platform"""
    system = platform.system().lower()
    if system == 'darwin':
        return 'macos'
    elif system in ['linux', 'windows']:
        return system
    else:
        print(f"⚠️  Unknown platform: {system}, defaulting to linux")
        return 'linux'

def main():
    """Main build process"""
    parser = argparse.ArgumentParser(description="Cross-platform build script for Nexus3 Tool")
    parser.add_argument('--platform', choices=list(PLATFORMS.keys()) + ['all', 'current'], 
                       default='current', help='Target platform to build for (default: current platform)')
    parser.add_argument('--clean', action='store_true', help='Clean build directories before building')
    
    args = parser.parse_args()
    
    print("🚀 Nexus3 Tool Cross-Platform Build Script")
    print("=" * 50)
    
    # Check if we're in the right directory
    if not Path("main.py").exists():
        print("❌ Error: main.py not found. Please run this script from the project root directory.")
        sys.exit(1)
    
    # Clean build directories if requested
    if args.clean:
        clean_build_dirs()
    
    # Install dependencies
    if not install_dependencies():
        print("❌ Failed to install dependencies")
        sys.exit(1)
    
    # Determine target platform
    if args.platform == 'current':
        target_platform = detect_current_platform()
        print(f"🔍 Detected current platform: {target_platform}")
    else:
        target_platform = args.platform
    
    # Build for specified platform(s)
    if target_platform == 'all':
        build_all_platforms()
    else:
        if build_for_platform(target_platform):
            print(f"\n✅ {target_platform} build completed successfully!")
        else:
            print(f"\n❌ {target_platform} build failed!")
            sys.exit(1)
    
    print("\n🎉 Build process completed!")
    print("\nUsage examples:")
    current_platform = platform.system().lower()
    if current_platform == 'darwin':
        current_platform = 'macos'
    
    for platform_name in PLATFORMS:
        platform_config = PLATFORMS[platform_name]
        # Use appropriate path separator for each platform
        if platform_name == 'windows':
            exe_path = f"dist\\{platform_name}\\{platform_config['executable_name']}"
        else:
            exe_path = f"dist/{platform_name}/{platform_config['executable_name']}"
        print(f"  {platform_name}: {exe_path} repo-list --help")

if __name__ == "__main__":
    main()
