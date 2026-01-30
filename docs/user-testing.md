# User Testing Checklist

Use this checklist to validate the end-to-end flow before a production rollout.

1. **Open the app**
   - Go to https://kass.freestorms.top.
   - Complete Telegram login.
   - Finish the onboarding wizard.

2. **Add a proxy**
   - Add a proxy in `host:port:user:pass` format.
   - Validate the proxy.
   - Confirm the proxy status is **active**.

3. **Add an account**
   - Add an account using a phone number.
   - Complete verification.
   - Confirm the account status is **verified**.

4. **Create a project**
   - Create a project.
   - Add a source and target.
   - Upload/import contacts.

5. **Create and run a campaign**
   - Create a campaign.
   - Start the campaign.
   - Confirm warming starts and dispatch logs appear.

6. **Admin checks**
   - Sign in as an admin user.
   - Check stats, tariffs, and backups.

**Expected results**
- No 5xx responses in API calls.
- WebSocket updates arrive for status changes.
- Backups appear in `/backups`.
