# Nexus3 Tool Makefile
# Provides convenient build targets for different platforms

.PHONY: help install clean build build-all build-windows build-linux build-macos test

# Default target
help:
	@echo "Nexus3 Tool Build System"
	@echo "========================"
	@echo ""
	@echo "Available targets:"
	@echo "  install      - Install Python dependencies"
	@echo "  clean        - Clean build directories"
	@echo "  build        - Build for current platform"
	@echo "  build-all    - Build for all platforms"
	@echo "  build-windows- Build for Windows"
	@echo "  build-linux  - Build for Linux"
	@echo "  build-macos  - Build for macOS"
	@echo "  test         - Run the tool with --help"
	@echo "  help         - Show this help message"

# Install dependencies
install:
	@echo "📦 Installing dependencies..."
	pip install -r requirements.txt

# Clean build directories
clean:
	@echo "🧹 Cleaning build directories..."
	rm -rf build dist __pycache__ scripts/__pycache__ scripts/functions/__pycache__
	find . -name "*.pyc" -delete
	find . -name "*.pyo" -delete
	find . -name "*.spec" -delete

# Build for current platform
build: install
	@echo "🔨 Building for current platform..."
	python build_cross_platform.py --platform current

# Build for all platforms
build-all: install
	@echo "🌍 Building for all platforms..."
	python build_cross_platform.py --platform all --clean

# Build for Windows
build-windows: install
	@echo "🪟 Building for Windows..."
	python build_cross_platform.py --platform windows

# Build for Linux
build-linux: install
	@echo "🐧 Building for Linux..."
	python build_cross_platform.py --platform linux

# Build for macOS
build-macos: install
	@echo "🍎 Building for macOS..."
	python build_cross_platform.py --platform macos

# Test the built executable
test:
	@echo "🧪 Testing built executable..."
	@if [ -f "dist/nexus3-tool" ]; then \
		./dist/nexus3-tool --help; \
	elif [ -f "dist/nexus3-tool.exe" ]; then \
		./dist/nexus3-tool.exe --help; \
	else \
		echo "❌ No executable found. Run 'make build' first."; \
	fi

# Development targets
dev-install: install
	@echo "🛠️  Installing development dependencies..."
	pip install -e .

# Quick development test
dev-test:
	@echo "🚀 Running development version..."
	python main.py --help
