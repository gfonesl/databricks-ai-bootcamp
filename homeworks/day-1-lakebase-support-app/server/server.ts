import { createApp, lakebase, server } from '@databricks/appkit';
import { setupSupportRoutes } from './routes/lakebase/support-routes';

createApp({
  plugins: [
    server(),
    lakebase(),
  ],
  async onPluginsReady(appkit) {
    await setupSupportRoutes(appkit);
  },
}).catch(console.error);
