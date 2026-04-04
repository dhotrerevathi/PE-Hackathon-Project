#!/bin/bash
# Allow the replicator user to connect for streaming replication from any host.
# This appends to pg_hba.conf which postgres reads on startup after init scripts run.
set -e
echo "host replication replicator all md5" >> "$PGDATA/pg_hba.conf"
echo "pg_hba.conf updated: replication user allowed."
