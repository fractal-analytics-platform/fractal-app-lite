#!/bin/sh
set -eu

exists() {
  command -v "$1" >/dev/null 2>&1
}

download() {
  curl -fsSL "$1" || wget -qO- "$1"
}

# Check requirements
if ! exists curl && ! exists wget; then
  echo "Error: neither curl nor wget was found. Please install curl or wget to continue." >&2
  exit 1
fi
if ! exists tar; then
  echo "Error: tar command not found. Please install tar to continue." >&2
  exit 1
fi

# Retrieve latest fractal-app-lite release tag by extracting it from the redirect header
LATEST_RELEASE_URL="https://github.com/fractal-analytics-platform/fractal-app-lite/releases/latest"
LATEST_RELEASE_AWK='BEGIN{IGNORECASE=1} /^[[:space:]]*Location:/ {sub(/\r$/, "", $2); sub(/.*\//, "", $2); print $2; exit}'

if exists curl; then
  VERSION=$(curl -sI "$LATEST_RELEASE_URL" | awk -F': ' "$LATEST_RELEASE_AWK")
else
  VERSION=$(wget --server-response --spider "$LATEST_RELEASE_URL" 2>&1 | awk -F': ' "$LATEST_RELEASE_AWK")
fi

echo ":: Downloading fractal-app-lite $VERSION"

FRACTAL_APP_LITE_DIR="$HOME/.fractal-app-lite"

if [ -d "$FRACTAL_APP_LITE_DIR" ]; then
  printf '%s [y/N] ' "Folder $FRACTAL_APP_LITE_DIR already exists. Do you want to overwrite a previous installation?"
  read answer
  case $answer in
    y|Y|yes|YES) ;;
    *) echo "Exiting."; exit 1 ;;
  esac
fi

rm -Rf "$FRACTAL_APP_LITE_DIR"
mkdir -p "$FRACTAL_APP_LITE_DIR/app"

FRACTAL_APP_LITE_RELEASE_URL="https://github.com/fractal-analytics-platform/fractal-app-lite/archive/refs/tags/$VERSION.tar.gz"

download "$FRACTAL_APP_LITE_RELEASE_URL" | tar --strip-components=1 -xz -C "$FRACTAL_APP_LITE_DIR/app"

echo ":: Installing pixi"

export PIXI_HOME="$FRACTAL_APP_LITE_DIR/.pixi"
# prevent adding PIXI_HOME to $PATH, to avoid conflict with others pixi installations
export PIXI_NO_PATH_UPDATE=1

download "https://pixi.sh/install.sh" | sh

export PATH="$PIXI_HOME/bin:$PATH"

cd "$FRACTAL_APP_LITE_DIR/app"
pixi install

echo ":: Downloading frontend static files"

FRACTAL_APP_LITE_FRONTEND_URL="https://github.com/fractal-analytics-platform/fractal-app-lite/releases/download/$VERSION/fractal-app-lite-frontend-$VERSION.tar.gz"
FRONTEND_BUILD_FOLDER="$FRACTAL_APP_LITE_DIR/app/src/frontend/build"
mkdir -p "$FRONTEND_BUILD_FOLDER"

download "$FRACTAL_APP_LITE_FRONTEND_URL" | tar -xz -C "$FRONTEND_BUILD_FOLDER"

echo "Successfully installed!"

mkdir -p "$FRACTAL_APP_LITE_DIR/bin"

FRACTAL_APP_SCRIPT="$FRACTAL_APP_LITE_DIR/bin/fractal-app-lite"

cat > "$FRACTAL_APP_SCRIPT" <<EOF
#!/bin/sh
export PATH="$PIXI_HOME/bin:\$PATH"
cd $FRACTAL_APP_LITE_DIR/app
pixi run app
EOF

chmod +x "$FRACTAL_APP_SCRIPT"

# Update ~/.bashrc, if the file exists
PATH_LINE="export PATH=\"${FRACTAL_APP_LITE_DIR}/bin:\$PATH\""
SHELL_CFG_FILE=~/.bashrc
if [ -f "$SHELL_CFG_FILE" ]; then
  # Append the line if not already present
  if ! grep -Fxq "$PATH_LINE" "$SHELL_CFG_FILE"; then
    echo "Updating '${SHELL_CFG_FILE}'"
    echo >>"$SHELL_CFG_FILE"
    echo "$PATH_LINE" >>"$SHELL_CFG_FILE"
    echo "Please restart or source your shell."
  fi
  echo ">>> You can run the app executing the fractal-app-lite command <<<"
else
  echo ">>> File $SHELL_CFG_FILE not found. You can run the app executing the script $FRACTAL_APP_SCRIPT <<<"
fi
