// CosmosDB Gremlin account for the OSDU Entitlements graph.
// Single-region, Session consistency, autoscale up to 4000 RU/s.

@description('CosmosDB Gremlin account name.')
param name string

@description('Azure region.')
param location string

resource gremlinAccount 'Microsoft.DocumentDB/databaseAccounts@2023-11-15' = {
  name: name
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
    capabilities: [
      {
        name: 'EnableGremlin'
      }
    ]
  }
}

resource gremlinDatabase 'Microsoft.DocumentDB/databaseAccounts/gremlinDatabases@2023-11-15' = {
  parent: gremlinAccount
  name: 'osdu-graph'
  properties: {
    resource: {
      id: 'osdu-graph'
    }
  }
}

resource entitlementsGraph 'Microsoft.DocumentDB/databaseAccounts/gremlinDatabases/graphs@2023-11-15' = {
  parent: gremlinDatabase
  name: 'Entitlements'
  properties: {
    resource: {
      id: 'Entitlements'
      partitionKey: {
        paths: [
          '/dataPartitionId'
        ]
        kind: 'Hash'
      }
    }
    options: {
      autoscaleSettings: {
        maxThroughput: 4000
      }
    }
  }
}

output resourceId string = gremlinAccount.id
output documentEndpoint string = gremlinAccount.properties.documentEndpoint
