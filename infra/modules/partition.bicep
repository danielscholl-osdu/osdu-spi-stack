// Per-partition data plane: CosmosDB SQL account with osdu-db (and
// optionally osdu-system-db on the primary partition), Service Bus
// namespace with topics and subscriptions, storage account with blob
// containers.
//
// Container, topic, subscription, and container-name definitions are
// ported literally from azure_infra.py (OSDU_DB_CONTAINERS,
// OSDU_SYSTEM_DB_CONTAINERS, SERVICEBUS_TOPICS, PARTITION_STORAGE_CONTAINERS).

@description('Data partition name, e.g. "opendes".')
param partition string

@description('Azure region.')
param location string

@description('CosmosDB SQL account name for this partition.')
param cosmosSqlName string

@description('Service Bus namespace name for this partition.')
param serviceBusName string

@description('Storage account name for this partition.')
param storageAccountName string

@description('True only for the primary partition; hosts osdu-system-db.')
param isPrimaryPartition bool = false

// ──────────────────────────────────────────────────────────
// Data definitions (ported from azure_infra.py)
// ──────────────────────────────────────────────────────────

var osduDbContainers = [
  { name: 'Authority', partitionKey: '/id' }
  { name: 'EntityType', partitionKey: '/id' }
  { name: 'FileLocationEntity', partitionKey: '/id' }
  { name: 'IngestionStrategy', partitionKey: '/workflowType' }
  { name: 'LegalTag', partitionKey: '/id' }
  { name: 'MappingInfo', partitionKey: '/sourceSchemaKind' }
  { name: 'RegisterAction', partitionKey: '/dataPartitionId' }
  { name: 'RegisterDdms', partitionKey: '/dataPartitionId' }
  { name: 'RegisterSubscription', partitionKey: '/dataPartitionId' }
  { name: 'RelationshipStatus', partitionKey: '/id' }
  { name: 'ReplayStatus', partitionKey: '/id' }
  { name: 'SchemaInfo', partitionKey: '/partitionId' }
  { name: 'Source', partitionKey: '/id' }
  { name: 'StorageRecord', partitionKey: '/id' }
  { name: 'StorageSchema', partitionKey: '/kind' }
  { name: 'TenantInfo', partitionKey: '/id' }
  { name: 'UserInfo', partitionKey: '/id' }
  { name: 'Workflow', partitionKey: '/workflowId' }
  { name: 'WorkflowCustomOperatorInfo', partitionKey: '/operatorId' }
  { name: 'WorkflowCustomOperatorV2', partitionKey: '/partitionKey' }
  { name: 'WorkflowRun', partitionKey: '/partitionKey' }
  { name: 'WorkflowRunV2', partitionKey: '/partitionKey' }
  { name: 'WorkflowRunStatus', partitionKey: '/partitionKey' }
  { name: 'WorkflowV2', partitionKey: '/partitionKey' }
]

var osduSystemDbContainers = [
  { name: 'Authority', partitionKey: '/id' }
  { name: 'EntityType', partitionKey: '/id' }
  { name: 'SchemaInfo', partitionKey: '/partitionId' }
  { name: 'Source', partitionKey: '/id' }
  { name: 'WorkflowV2', partitionKey: '/partitionKey' }
]

var serviceBusTopicDefs = [
  { name: 'indexing-progress', maxSizeInMegabytes: 1024 }
  { name: 'legaltags', maxSizeInMegabytes: 1024 }
  { name: 'recordstopic', maxSizeInMegabytes: 1024 }
  { name: 'recordstopicdownstream', maxSizeInMegabytes: 1024 }
  { name: 'recordstopiceg', maxSizeInMegabytes: 1024 }
  { name: 'schemachangedtopic', maxSizeInMegabytes: 1024 }
  { name: 'schemachangedtopiceg', maxSizeInMegabytes: 1024 }
  { name: 'legaltagschangedtopiceg', maxSizeInMegabytes: 1024 }
  { name: 'statuschangedtopic', maxSizeInMegabytes: 5120 }
  { name: 'statuschangedtopiceg', maxSizeInMegabytes: 1024 }
  { name: 'recordstopic-v2', maxSizeInMegabytes: 1024 }
  { name: 'reindextopic', maxSizeInMegabytes: 1024 }
  { name: 'entitlements-changed', maxSizeInMegabytes: 1024 }
  { name: 'replaytopic', maxSizeInMegabytes: 1024 }
]

// Flat subscription list. Bicep for-loops cannot nest inside flatten() at
// var-declaration time, so topic/sub pairs are enumerated explicitly.
// "entitlements-changed" has no subscriptions and is intentionally omitted.
var serviceBusSubscriptionDefs = [
  { topicName: 'indexing-progress', subName: 'indexing-progresssubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'legaltags', subName: 'legaltagssubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'recordstopic', subName: 'recordstopicsubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'recordstopic', subName: 'wkssubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'recordstopicdownstream', subName: 'downstreamsub', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'recordstopiceg', subName: 'eg_sb_wkssubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'schemachangedtopic', subName: 'schemachangedtopicsubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'schemachangedtopiceg', subName: 'eg_sb_schemasubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'legaltagschangedtopiceg', subName: 'eg_sb_legaltagssubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'statuschangedtopic', subName: 'statuschangedtopicsubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'statuschangedtopiceg', subName: 'eg_sb_statussubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'recordstopic-v2', subName: 'recordstopic-v2-subscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'reindextopic', subName: 'reindextopicsubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
  { topicName: 'replaytopic', subName: 'replaytopicsubscription', maxDeliveryCount: 5, lockDuration: 'PT5M' }
]

var partitionStorageContainerNames = [
  'legal-service-azure-configuration'
  'osdu-wks-mappings'
  'wdms-osdu'
  'file-staging-area'
  'file-persistent-area'
]

// ──────────────────────────────────────────────────────────
// CosmosDB SQL
// ──────────────────────────────────────────────────────────

resource cosmosAccount 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: cosmosSqlName
  location: location
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    locations: [
      {
        locationName: location
        failoverPriority: 0
        isZoneRedundant: false
      }
    ]
  }
}

resource osduDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-11-15' = {
  parent: cosmosAccount
  name: 'osdu-db'
  properties: {
    resource: {
      id: 'osdu-db'
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 4000
      }
    }
  }
}

resource osduDbContainerResources 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = [for container in osduDbContainers: {
  parent: osduDb
  name: container.name
  properties: {
    resource: {
      id: container.name
      partitionKey: {
        paths: [
          container.partitionKey
        ]
        kind: 'Hash'
      }
    }
  }
}]

resource osduSystemDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2023-11-15' = if (isPrimaryPartition) {
  parent: cosmosAccount
  name: 'osdu-system-db'
  properties: {
    resource: {
      id: 'osdu-system-db'
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 4000
      }
    }
  }
}

resource osduSystemDbContainerResources 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2023-11-15' = [for container in osduSystemDbContainers: if (isPrimaryPartition) {
  parent: osduSystemDb
  name: container.name
  properties: {
    resource: {
      id: container.name
      partitionKey: {
        paths: [
          container.partitionKey
        ]
        kind: 'Hash'
      }
    }
  }
}]

// ──────────────────────────────────────────────────────────
// Service Bus
// ──────────────────────────────────────────────────────────

resource serviceBusNamespace 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' = {
  name: serviceBusName
  location: location
  sku: {
    name: 'Standard'
    tier: 'Standard'
  }
}

resource serviceBusTopics 'Microsoft.ServiceBus/namespaces/topics@2022-10-01-preview' = [for topic in serviceBusTopicDefs: {
  parent: serviceBusNamespace
  name: topic.name
  properties: {
    maxSizeInMegabytes: topic.maxSizeInMegabytes
  }
}]

resource serviceBusSubscriptions 'Microsoft.ServiceBus/namespaces/topics/subscriptions@2022-10-01-preview' = [for sub in serviceBusSubscriptionDefs: {
  name: '${serviceBusName}/${sub.topicName}/${sub.subName}'
  properties: {
    maxDeliveryCount: sub.maxDeliveryCount
    lockDuration: sub.lockDuration
  }
  dependsOn: [
    serviceBusTopics
  ]
}]

// ──────────────────────────────────────────────────────────
// Storage
// ──────────────────────────────────────────────────────────

resource storageAccount 'Microsoft.Storage/storageAccounts@2023-01-01' = {
  name: storageAccountName
  location: location
  kind: 'StorageV2'
  sku: {
    name: 'Standard_LRS'
  }
  properties: {
    accessTier: 'Hot'
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: true
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-01-01' = {
  parent: storageAccount
  name: 'default'
}

resource storageContainerResources 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-01-01' = [for containerName in partitionStorageContainerNames: {
  parent: blobService
  name: containerName
}]

// ──────────────────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────────────────

output partition string = partition
output cosmosAccountId string = cosmosAccount.id
output cosmosEndpoint string = cosmosAccount.properties.documentEndpoint
output serviceBusId string = serviceBusNamespace.id
output storageId string = storageAccount.id
