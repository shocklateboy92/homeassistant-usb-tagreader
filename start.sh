#!/bin/bash

# Startup script for NFC Reader with built-in PCSCD support

# Function to log with timestamp
log_info() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] $1"
}

log_error() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') [ERROR] $1" >&2
}

# Check if a host pcscd socket is already mounted
if [ -S /run/pcscd/pcscd.comm ]; then
    log_info "Using host PCSCD daemon (socket found at /run/pcscd/pcscd.comm)"
else
    log_info "No host PCSCD socket found, starting pcscd inside container..."
    mkdir -p /run/pcscd
    pcscd --foreground --auto-exit --disable-polkit &
    PCSCD_PID=$!
    # Give pcscd a moment to start and detect readers
    sleep 2

    if ! kill -0 "$PCSCD_PID" 2>/dev/null; then
        log_error "pcscd failed to start"
        exit 1
    fi
    log_info "pcscd started (PID $PCSCD_PID)"
fi

log_info "Starting NFC Reader application..."
cd /app
su -s /bin/bash -c "python nfc_reader.py" nfcuser
ret=$?

if [ $ret -ne 0 ]; then
    log_error "NFC Reader application exited with error code $ret."
    log_info "Waiting for 65 seconds before exiting..."
    sleep 65
else
    log_info "NFC Reader application exited normally."
fi