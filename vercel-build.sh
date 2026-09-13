#!/bin/bash
echo "Installing dependencies..."
pip install -r requirements.txt

echo "Initializing database..."
python cli.py init

echo "Building a lightweight 14-day database for Vercel deployment (to stay under the 250MB size limit)..."
python cli.py backfill --days 14

echo "Computing index..."
python cli.py index

echo "Removing database exclusion from .gitignore so Vercel packages it..."
sed -i 's|data/\*.db||g' .gitignore

echo "Build complete."
