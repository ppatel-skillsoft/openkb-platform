#!/bin/bash

# Script to export Structurizr diagrams and generate a static HTML page.
# Usage: ./export.sh

set -e

WORKSPACE_FILE="workspace.dsl"
EXPORT_DIR="docs"
CUSTOM_FONT="Google Sans, sans-serif"

echo "Starting Structurizr export..."

if [ ! -f "$WORKSPACE_FILE" ]; then
  echo "Workspace file '$WORKSPACE_FILE' not found in $(pwd)"
  exit 1
fi

if [ -d "$EXPORT_DIR" ]; then
  echo "Cleaning previous export..."
  rm -rf "$EXPORT_DIR"
fi

mkdir -p "$EXPORT_DIR" && chmod 777 "$EXPORT_DIR"

echo "Exporting workspace to static HTML..."
podman run --rm \
  -v "$(pwd):/work" \
  structurizr/structurizr export \
  -workspace "/work/$WORKSPACE_FILE" \
  -format static \
  -output "/work/$EXPORT_DIR"

echo "Applying custom font: $CUSTOM_FONT"
if [ -f "$EXPORT_DIR/css/structurizr.css" ]; then
  sed -i '' "s/font-family: Tahoma, Verdana, Helvetica, Arial, sans-serif;/font-family: $CUSTOM_FONT;/g" "$EXPORT_DIR/css/structurizr.css"
fi

if [ -f "$EXPORT_DIR/js/structurizr-ui.js" ]; then
  sed -i '' "s/structurizr.ui.DEFAULT_FONT_NAME = 'Tahoma, Verdana, Helvetica, Arial';/structurizr.ui.DEFAULT_FONT_NAME = '$CUSTOM_FONT';/g" "$EXPORT_DIR/js/structurizr-ui.js"
fi

if [ -f "$EXPORT_DIR/index.html" ]; then
  sed -i '' '/<head>/a\
    <link rel="preconnect" href="https://fonts.googleapis.com">\
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\
    <link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap" rel="stylesheet">\
' "$EXPORT_DIR/index.html"
fi

echo "Renaming Structurizr page to diagrams.html"
mv "$EXPORT_DIR/index.html" "$EXPORT_DIR/diagrams.html"

echo "Generating index.html portal"
cat > "$EXPORT_DIR/index.html" <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>OpenKB Platform - Architecture</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Google+Sans:wght@400;500;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Google Sans', system-ui, sans-serif; margin: 0; background: #f8fafc; color: #0f172a; }
    .wrap { max-width: 960px; margin: 48px auto; padding: 0 24px; }
    .card { background: #fff; border: 1px solid #e2e8f0; border-radius: 12px; padding: 24px; }
    h1 { margin: 0 0 10px; font-size: 28px; }
    p { margin: 0 0 20px; color: #475569; }
    a.btn { display: inline-block; text-decoration: none; background: #2563eb; color: #fff; padding: 10px 16px; border-radius: 8px; font-weight: 600; }
    a.btn:hover { background: #1d4ed8; }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="card">
      <h1>OpenKB Platform</h1>
      <p>C4 Level 2 Container diagram exported from Structurizr DSL.</p>
      <a class="btn" href="./diagrams.html">Open Diagrams</a>
    </div>
  </div>
</body>
</html>
EOF

echo "Done. Open $EXPORT_DIR/index.html"
