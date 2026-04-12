#!/bin/bash
# Goose Guard — one-shot setup script for Raspberry Pi
# Run this once on a fresh Raspberry Pi OS Lite installation.
# Usage: bash install.sh

set -e

INSTALL_DIR="/home/pi/goose-guard"
echo "=== Goose Guard Installer ==="

# 1. System updates
echo "Updating system packages..."
sudo apt update && sudo apt upgrade -y

# 2. Install audio and system dependencies
echo "Installing dependencies..."
sudo apt install -y python3-pip python3-venv alsa-utils mpg123 libsdl2-mixer-2.0-0

# 3. Create virtual environment
echo "Setting up Python environment..."
python3 -m venv "$INSTALL_DIR/venv"
source "$INSTALL_DIR/venv/bin/activate"

# 4. Install Python dependencies
pip install --upgrade pip
pip install -r "$INSTALL_DIR/requirements.txt"

# 5. Set audio output to 3.5mm jack (not HDMI)
# numid=3: 0=auto, 1=3.5mm, 2=HDMI
sudo amixer cset numid=3 1 2>/dev/null || echo "Audio config: using default output"

# 6. Create sound directories if they don't exist
mkdir -p "$INSTALL_DIR/sounds/predator"
mkdir -p "$INSTALL_DIR/sounds/distress"
mkdir -p "$INSTALL_DIR/sounds/startle"
mkdir -p "$INSTALL_DIR/sounds/custom"

# 7. Install systemd service
echo "Installing systemd service..."
sudo cp "$INSTALL_DIR/goose-guard.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable goose-guard
sudo systemctl start goose-guard

# 8. Set hostname for easy network access
echo "Setting hostname to gooseguard..."
sudo hostnamectl set-hostname gooseguard

echo ""
echo "================================================"
echo "  Goose Guard installed successfully!"
echo ""
echo "  After reboot, access the control panel at:"
echo "  http://gooseguard.local:5000"
echo ""
echo "  Next steps:"
echo "  1. Add .mp3 sound files to $INSTALL_DIR/sounds/"
echo "  2. Reboot: sudo reboot"
echo "  3. Open the URL above on your phone"
echo "================================================"
