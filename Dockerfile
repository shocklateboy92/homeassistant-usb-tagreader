ARG PYTHON_VARIANT=slim
ARG DEV_MODE=false
ARG PYTHON_RELEASE=3.11
FROM python:${PYTHON_RELEASE}${PYTHON_VARIANT:+-$PYTHON_VARIANT}

# Re-declare after FROM to make it available in subsequent layers
ARG DEV_MODE=false
ARG PYTHON_RELEASE

# Install system dependencies for PCSC (daemon + client libraries + CCID driver)
RUN apt-get update && apt-get install -y \
    pcscd \
    libpcsclite-dev \
    libpcsclite1 \
    libccid \
    pcsc-tools \
    python3-pyscard \
    libusb-1.0-0-dev \
    pkg-config \
    gcc \
    swig \
    procps \
    && rm -rf /var/lib/apt/lists/*

# Conditionally install sudo and vsmartcard for development only
RUN <<EOF
if [ "$DEV_MODE" = "true" ]; then
    set -e

    echo "Installing development packages..."
    apt-get update
    apt-get install -y sudo pcscd vsmartcard-vpcd vsmartcard-vpicc python3-virtualsmartcard jq help2man mosquitto
    rm -rf /var/lib/apt/lists/*

    pip install flake8 black mypy pylint pytest pytest-cov

    echo "Installing latest vsmartcard from GitHub..."
    LATEST_VSMARTCARD=$(curl -H "Accept: application/json" -s https://api.github.com/repos/frankmorgner/vsmartcard/releases/latest | jq -r '.tag_name')
    wget "https://github.com/frankmorgner/vsmartcard/releases/download/$LATEST_VSMARTCARD/$LATEST_VSMARTCARD.tar.gz"
    tar -xzf "$LATEST_VSMARTCARD.tar.gz"
    cd $LATEST_VSMARTCARD
    autoreconf --verbose --install
    ./configure --sysconfdir=/etc
    make
    make install

    echo "nfcuser ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/nfcuser

    echo "Development packages installed successfully"
else
    echo "Skipping development packages (DEV_MODE='$DEV_MODE')"
fi
EOF

# Create app directory
WORKDIR /app

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code and startup script
COPY *.py .
COPY start.sh .
RUN chmod +x start.sh

# Create a non-root user for running the application
RUN useradd -m -u 1000 -s /bin/bash nfcuser && \
    chown -R nfcuser:nfcuser /app

# pcscd needs root to access USB devices, so we run as root
# start.sh will start pcscd and then drop to nfcuser for the app
CMD ["./start.sh"]