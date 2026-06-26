# GraphGraph Setup Bootstrap for Windows
Write-Host "Starting GraphGraph Setup..." -ForegroundColor Cyan

# Check if Python is installed
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Error: Python is not installed or not in PATH. Please install Python 3.10+." -ForegroundColor Red
    Exit 1
}

# Run the setup Python script
python setup_graphgraph.py $args
