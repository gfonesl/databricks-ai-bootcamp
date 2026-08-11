-- Template: replace every <...> value with your own deployment details.
-- Never paste a raw secret in this file or in the SQL editor.
CREATE CONNECTION weather_mcp_connection TYPE HTTP
OPTIONS (
  host 'https://<YOUR_MCP_APP_HOST>',
  port '443',
  base_path '/mcp',
  client_id '<OAUTH_CLIENT_ID>',
  client_secret secret('<SECRET_SCOPE>', '<SECRET_KEY>'),
  oauth_scope 'all-apis',
  token_endpoint 'https://<YOUR_WORKSPACE_HOST>/oidc/v1/token',
  is_mcp_connection 'true'
);

-- After creating the Agent Bricks agent, grant its service principal access:
-- GRANT USE CONNECTION ON CONNECTION weather_mcp_connection TO `<agent-service-principal-client-id>`;
