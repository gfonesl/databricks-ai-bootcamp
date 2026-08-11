-- Run in a SQL editor after the OAuth secret has been saved directly in the scope.
-- Never paste the OAuth secret in this file or in the SQL editor.
CREATE CONNECTION tripwise_mcp_connection TYPE HTTP
OPTIONS (
  host 'https://tripwise-capstone-7474646632333305.aws.databricksapps.com',
  port '443',
  base_path '/mcp/',
  client_id '674108cd-429b-4ad0-9ed1-30cae2727f14',
  client_secret secret('tripwise-agent-secrets', 'agent-oauth-client-secret'),
  oauth_scope 'all-apis',
  token_endpoint 'https://dbc-a2b59cb4-753d.cloud.databricks.com/oidc/v1/token',
  is_mcp_connection 'true'
);

-- After creating the Supervisor Agent, grant it access to this connection.
-- GRANT USE CONNECTION ON tripwise_mcp_connection TO `<tripwise-agent-service-principal-id>`;
