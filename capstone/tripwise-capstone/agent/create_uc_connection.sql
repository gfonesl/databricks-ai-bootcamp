-- Template: replace every <...> value with your own deployment details.
-- Run in a SQL editor after the OAuth secret has been saved directly in the scope.
-- Never paste the OAuth secret in this file or in the SQL editor.
CREATE CONNECTION tripwise_mcp_connection TYPE HTTP
OPTIONS (
  host '<YOUR_TRIPWISE_APP_HOST>',
  port '443',
  base_path '/mcp/',
  client_id '<OAUTH_CLIENT_ID>',
  client_secret secret('<SECRET_SCOPE>', '<SECRET_KEY>'),
  oauth_scope 'all-apis',
  token_endpoint 'https://<YOUR_WORKSPACE_HOST>/oidc/v1/token',
  is_mcp_connection 'true'
);

-- After creating the Supervisor Agent, grant it access to this connection.
-- GRANT USE CONNECTION ON tripwise_mcp_connection TO `<tripwise-agent-service-principal-id>`;
