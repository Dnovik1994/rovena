# Smoke Test Checklist

Run this checklist after deploy to validate the core flow quickly.

1. **Login**
   - Open the Telegram WebApp.
   - Complete authentication.

2. **Onboarding**
   - Finish the onboarding flow without errors.

3. **Proxy**
   - Add a proxy.
   - Validate it.
   - Ensure status becomes **active**.

4. **Account**
   - Add an account.
   - Complete verification.
   - Ensure status becomes **verified**.

5. **Project & campaign**
   - Create a project.
   - Create a campaign.
   - Start the campaign.
   - Confirm logs/dispatch activity.

6. **Admin checks**
   - Login as admin.
   - Verify stats and tariffs load.

7. **Monitoring & backups**
   - Check `/metrics` endpoint.
   - Open Grafana and confirm Prometheus datasource.
   - Verify backups exist in `/backups`.
