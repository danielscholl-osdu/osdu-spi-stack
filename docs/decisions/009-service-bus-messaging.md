# ADR-009: Azure Service Bus for Messaging

**Status:** Accepted

## Context

OSDU services use asynchronous messaging for event-driven workflows: record change notifications, legal tag changes, schema changes, indexing progress, and workflow events. A cloud-agnostic approach uses in-cluster RabbitMQ with 40+ exchanges, queues, and bindings.

The Azure SPI services are built against the Service Bus SDK. They expect Service Bus topic/subscription semantics, not AMQP exchange/queue bindings.

## Decision

Use Azure Service Bus with 14 topics per data partition, matching the osdu-spi-infra reference:

| Topic | Purpose |
|-------|---------|
| `recordstopic` | Record create/update events |
| `recordstopic-v2` | V2 record events |
| `recordstopicdownstream` | Downstream record processing |
| `legaltags` | Legal tag changes |
| `legaltagschangedtopiceg` | Legal tag change notifications (Event Grid pattern) |
| `schemachangedtopic` | Schema changes |
| `indexing-progress` | Indexing status updates |
| `statuschangedtopic` | Status change events |
| `reindextopic` | Reindex requests |
| `replaytopic` | Replay events |
| `entitlements-changed` | Entitlements modifications |
| `recordstopiceg` | Record events (Event Grid pattern) |
| `schemachangedtopiceg` | Schema events (Event Grid pattern) |
| `statuschangedtopiceg` | Status events (Event Grid pattern) |

## Consequences

- Service Bus is provisioned per partition; multi-partition deployments get independent namespaces.
- Standard SKU provides sufficient throughput for development/testing; Premium SKU available for production.
- Topic subscriptions handle fan-out; indexer-queue subscribes to record and schema topics.
- No in-cluster messaging infrastructure to manage; Azure handles availability and scaling.
- Service Bus access uses Workload Identity (Azure Service Bus Data Sender/Receiver roles).
