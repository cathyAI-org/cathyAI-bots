#!/bin/bash
# Setup script for Catcord Bots Framework

echo "Setting up Catcord Bots Framework..."
echo ""
echo "Choose setup mode:"
echo "  1) Docker (production deployment)"
echo "  2) Local Python (development)"
read -p "Enter choice [1-2]: " choice

if [ "$choice" = "1" ]; then
    # Docker setup
    if ! command -v docker &> /dev/null; then
        echo "❌ Docker not found. Please install Docker"
        exit 1
    fi
    echo "✓ Docker found: $(docker --version)"

    if ! command -v docker-compose &> /dev/null; then
        echo "❌ docker-compose not found. Please install docker-compose"
        exit 1
    fi
    echo "✓ docker-compose found: $(docker-compose --version)"

    if [ ! -f "config.yaml" ]; then
        if [ -f "config.yaml.template" ]; then
            cp config.yaml.template config.yaml
            echo "✓ config.yaml created (please configure it)"
        fi
    else
        echo "✓ config.yaml exists"
    fi

    echo "Building framework base image..."
    docker build -t catcord-bots-framework:latest ./framework
    [ $? -ne 0 ] && echo "❌ Framework build failed" && exit 1
    echo "✓ Framework image built"

    echo "Building bot images..."
    docker-compose -f docker-compose.bots.yml build
    [ $? -ne 0 ] && echo "❌ Bot build failed" && exit 1
    echo "✓ Bot images built"

    echo ""
    echo "✅ Docker setup complete!"
    echo "Run: docker-compose -f docker-compose.bots.yml run --rm cleaner --config /config/config.yaml --mode pressure --dry-run"

elif [ "$choice" = "2" ]; then
    # Local Python setup
    if ! command -v python3 &> /dev/null; then
        echo "❌ Python 3 not found"
        exit 1
    fi
    echo "✓ Python found: $(python3 --version)"

    if [ ! -d "venv" ]; then
        python3 -m venv venv
        echo "✓ Virtual environment created"
    else
        echo "✓ Virtual environment exists"
    fi

    source venv/bin/activate
    pip install --upgrade pip -q
    pip install -r requirements.txt
    echo "✓ Dependencies installed"

    if [ ! -f "config.yaml" ]; then
        if [ -f "config.yaml.template" ]; then
            cp config.yaml.template config.yaml
            echo "✓ config.yaml created (please configure it)"
        fi
    else
        echo "✓ config.yaml exists"
    fi

    echo ""
    echo "✅ Local setup complete!"
    echo "Activate: source venv/bin/activate"
    echo "Run: python main.py --config config.yaml --mode pressure --dry-run"
else
    echo "Invalid choice"
    exit 1
fi
