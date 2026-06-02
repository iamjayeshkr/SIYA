#!/bin/bash
# Fix numpy/ONNX Runtime incompatibility crash

echo "🔧 Fixing numpy/ONNX Runtime crash..."
echo ""

# Recreate venv from scratch
echo "Step 1: Backing up requirements..."
./venv311/bin/pip freeze > /tmp/vani_requirements_backup.txt

echo "Step 2: Removing old venv..."
rm -rf ./venv311

echo "Step 3: Creating fresh venv..."
python3.11 -m venv ./venv311

echo "Step 4: Upgrading pip..."
./venv311/bin/pip install --upgrade pip

echo "Step 5: Installing numpy 1.26.4 (compatible version)..."
./venv311/bin/pip install "numpy==1.26.4"

echo "Step 6: Installing ONNX Runtime 1.26.0 (latest)..."
./venv311/bin/pip install "onnxruntime==1.26.0"

echo "Step 7: Reinstalling other dependencies..."
./venv311/bin/pip install -r requirements/base.txt
./venv311/bin/pip install -r requirements/mac.txt

echo ""
echo "✅ Fix complete!"
echo ""
echo "Testing compatibility..."
./venv311/bin/python3 -c "import numpy; import onnxruntime; print(f'✅ Numpy {numpy.__version__}'); print(f'✅ ONNX Runtime {onnxruntime.__version__}'); print('✅ Compatible!')"

echo ""
echo "🎉 VANI should now start without segfaults!"
echo ""
echo "To start VANI:"
echo "  python -m vani.launcher"
