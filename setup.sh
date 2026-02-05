#!/bin/bash
# Setup script for Linux development

set -e

echo "=== Setting up Video Processing Pipeline ==="

# Check if ffmpeg is installed
if ! command -v ffmpeg &> /dev/null; then
    echo "❌ ffmpeg not found. Please install it:"
    echo "   Ubuntu/Debian: sudo apt-get install ffmpeg"
    echo "   macOS: brew install ffmpeg"
    exit 1
fi

if ! command -v ffprobe &> /dev/null; then
    echo "❌ ffprobe not found. Please install ffmpeg."
    exit 1
fi

echo "✓ ffmpeg found: $(ffmpeg -version | head -1)"

# Install Python dependencies
echo ""
echo "Installing Python dependencies..."
pip install -r requirements.txt

# Download Vosk model if not exists
MODEL_DIR="vosk-model-small-ru-0.22"
if [ ! -d "$MODEL_DIR" ]; then
    echo ""
    echo "Downloading Vosk Russian model..."
    wget https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip
    unzip vosk-model-small-ru-0.22.zip
    rm vosk-model-small-ru-0.22.zip
    echo "✓ Model downloaded to $MODEL_DIR/"
else
    echo "✓ Vosk model already exists"
fi

# Setup fonts
FONT_DIR="assets/oswald/static"
if [ ! -d "$FONT_DIR" ]; then
    echo ""
    echo "Setting up Oswald fonts..."
    mkdir -p "$FONT_DIR"
    
    # Download Oswald from Google Fonts
    wget -O oswald.zip "https://fonts.google.com/download?family=Oswald"
    unzip -o oswald.zip -d "$FONT_DIR/.."
    rm -f oswald.zip
    
    # Find and move the bold font if needed
    if [ -f "$FONT_DIR/../Oswald-Bold.ttf" ]; then
        mv "$FONT_DIR/../Oswald-Bold.ttf" "$FONT_DIR/"
    fi
    
    echo "✓ Fonts setup complete"
else
    echo "✓ Fonts already setup"
fi

echo ""
echo "=== Setup complete! ==="
echo ""
echo "Run the script with:"
echo "  python pipeline_vosk.py              # GUI mode"
echo "  python pipeline_vosk.py -i video.mp4 -o ./out  # CLI mode"
