-- Create a dedicated replication user for the read replica.
-- (document: §Database replication — master/slave relationship)
CREATE USER replicator WITH REPLICATION LOGIN PASSWORD 'replicator_pass';
