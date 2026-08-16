#!/usr/bin/env bash
# Restart all core services
# Usage: ./restart-all.sh

./stop-all.sh
sleep 3
./start-all.sh
