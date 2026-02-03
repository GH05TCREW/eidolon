// Node constraints
CREATE CONSTRAINT asset_node_id IF NOT EXISTS FOR (n:Asset) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT network_node_id IF NOT EXISTS FOR (n:NetworkContainer) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT identity_node_id IF NOT EXISTS FOR (n:Identity) REQUIRE n.node_id IS UNIQUE;
CREATE CONSTRAINT policy_node_id IF NOT EXISTS FOR (n:Policy) REQUIRE n.node_id IS UNIQUE;

// Evidence nodes
CREATE CONSTRAINT evidence_source IF NOT EXISTS FOR (e:Evidence) REQUIRE (e.source_type, e.source_id) IS NODE KEY;
CREATE CONSTRAINT edge_evidence_id IF NOT EXISTS FOR (e:EdgeEvidence) REQUIRE e.edge_id IS UNIQUE;

// Common indexes for traversal
CREATE INDEX asset_identifier IF NOT EXISTS FOR (n:Asset) ON (n.identifiers);
CREATE INDEX network_cidr IF NOT EXISTS FOR (n:NetworkContainer) ON (n.cidr);
CREATE INDEX identity_name IF NOT EXISTS FOR (n:Identity) ON (n.name);
