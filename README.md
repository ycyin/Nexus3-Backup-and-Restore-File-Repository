# Nexus Repository Backup and Restore

This project provides a set of commands to backup and restore files in a Nexus Repository. It uses the Typer library to create a command-line interface (CLI).

## Installation

Before running the commands, make sure you have Python 3.12 or later installed. Then, install the required libraries with pip:

```bash
pip install -r requirements.txt
```

## Usage

The CLI provides three commands: `repo-list`, `download`, and `upload`.

### repo-list

The `repo-list` command retrieves a list of repositories from a Nexus server.

```bash
python scripts repo-list --nexus-base-url http://example.com:8081 --username <username> --password <password>
```

### download

The `download` command downloads components from a Nexus repository to a local directory.

```bash
python scripts download --nexus-base-url http://example.com:8081 --repo-name <repository-name> --username <username> --password <password> --destination <path>
```

#### Download Command Options

| Option         | Default Value       | Description                       |
|----------------|---------------------|-----------------------------------|
| nexus-base-url | <http://localhost:8081> | The repository URL                |
| repo-name      | pypi-all            | The repository name               |
| username       | admin               | The username for authentication   |
| password       | admin123            | The password for authentication   |
| destination    | backup              | The destination for backup        |

### upload

The `upload` command uploads components from a local directory to a Nexus repository.

```bash
python scripts upload --nexus-base-url http://example.com:8081 --repo-name <repository-name> --username <username> --password <password> --source-directory <path>
```

#### Upload Command Options

| Option           | Default Value       | Description                       |
|------------------|---------------------|-----------------------------------|
| nexus-base-url   | http://localhost:8081 | The repository URL                |
| repo-name        | pypi-all            | The repository name               |
| username         | admin               | The username for authentication   |
| password         | admin123            | The password for authentication   |
| source-directory | backup              | The source directory for restore  |

In these commands, replace `http://example.com:8081`, `<repository-name>`, `<username>`, `<password>`, and `<path>` with your Nexus server URL, repository name, username, password, and the path to the local directory, respectively.

#### Important Notes for `upload` Command

When using the `upload` command, the tool will perform the following steps to ensure correctness:

1.  **Directory Validation**: It first checks if the provided `--source-directory` exists and is a valid directory.
2.  **User Confirmation**: Before starting the upload, it will prominently display the source directory and ask for your confirmation. This is a crucial step to prevent accidental uploads from the wrong location.

    ```
    ======================================================================
    UPLOAD SOURCE DIRECTORY
    /path/to/your/backup/repository/maven-releases
    ======================================================================

    📁 Expected directory structure:
       For Maven repositories:
         source_directory/
         └── com/org/net/...
             └── [groupId path]/
                 └── [artifactId]/
                     └── [version]/
                         ├── artifact-version.jar
                         ├── artifact-version.pom
                         └── artifact-version-sources.jar

       For other repository types:
         source_directory/
         └── [your files and folders]

    Do you confirm this is the correct source directory to upload from? [y/N]: y
    ```

3.  **Maven Coordinate Parsing**: For Maven repositories, the tool uses a **POM-first** strategy:

    *   **Primary Method (Recommended)**: It first searches for a corresponding `.pom` file for each artifact. If found, it parses the `groupId`, `artifactId`, and `version` directly from the POM file, which is the most accurate source of information.
    *   **Fallback Method**: **Only if a `.pom` file is not found**, the tool will fall back to parsing the coordinates from the directory structure relative to the `--source-directory`. For this to work, it is essential that your source directory contains the standard Maven layout (e.g., `com/mycompany/app/1.0/...`).

## Building Standalone Executables

You can build standalone executables that don't require Python to be installed on the target machine. This makes it easy to distribute and run the tool on systems without Python environments.

### Prerequisites

- Python 3.12 or later
- pip (Python package installer)

### Quick Build

For a simple build on your current platform:

```bash
# Using Makefile (Linux/macOS - Recommended)
make build

# Using cross-platform Python script
python build_cross_platform.py --platform $(uname -s | tr '[:upper:]' '[:lower:]')

# Or let it auto-detect your platform
python build_cross_platform.py
```

### Cross-Platform Build

To build executables for multiple platforms:

```bash
# Using Makefile (Linux/macOS)
make build-all          # Build for all platforms
make build-windows      # Build for Windows only
make build-linux        # Build for Linux only
make build-macos        # Build for macOS only
make clean              # Clean build directories

# Using Python script directly
python build_cross_platform.py --platform all
python build_cross_platform.py --platform windows
python build_cross_platform.py --platform linux
python build_cross_platform.py --platform macos
python build_cross_platform.py --platform all --clean
```

### Build Output

After successful build, you'll find executables in the `dist/` directory:

```
dist/
├── windows/
│   └── nexus3-tool.exe
├── linux/
│   └── nexus3-tool
└── macos/
    └── nexus3-tool
```

### Using the Executables

The built executables are self-contained and can be run directly:

```bash
# Linux/macOS
./dist/linux/nexus3-tool repo-list --help
./dist/linux/nexus3-tool download --nexus-base-url http://your-nexus:8081

# Windows
dist\windows\nexus3-tool.exe repo-list --help
dist\windows\nexus3-tool.exe download --nexus-base-url http://your-nexus:8081
```

### Build Features

- **Cross-platform support**: Build for Windows, Linux, and macOS
- **Single executable**: All dependencies bundled into one file
- **No Python required**: Run on machines without Python installed
- **Automatic cleanup**: Cleans previous builds automatically
- **Size optimization**: Uses UPX compression when available
- **Platform detection**: Automatically detects and builds for current platform

### Troubleshooting Build Issues

1. **Missing Dependencies**: Ensure all requirements are installed:
   ```bash
   pip install -r requirements.txt
   ```

2. **PyInstaller Errors**: Try cleaning the build cache:
   ```bash
   python build_cross_platform.py --clean
   ```

3. **Permission Issues**: On Linux/macOS, make sure the build script is executable:
   ```bash
   chmod +x build_cross_platform.py
   ```

4. **Large Executable Size**: This is normal for bundled executables. The tool includes the Python interpreter and all dependencies.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.
