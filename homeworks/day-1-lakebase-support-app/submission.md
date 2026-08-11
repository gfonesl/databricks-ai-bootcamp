# Day 1 Homework Submission - Lakebase Support App

## App URL

https://day1-support-app-7474646632333305.aws.databricksapps.com

## Evidence checklist

- [x] Screenshot of the deployed Databricks App
- [x] Screenshot of Lakebase tables `support_app.tickets` and `support_app.ticket_messages`
- [x] Source ZIP generated without `.env`, credentials, `.agents/`, or `.ai-dev-kit/`
- [ ] Existing tickets, a new ticket, a new message, and a status update verified after refresh

## Reflection

The most difficult part was designing the Lakebase permission flow correctly: the app service principal must create and own the `support_app` schema on its first deployment. Lakebase is suited to this operational workflow because it offers low-latency PostgreSQL reads and writes with foreign keys, whereas a traditional analytics table is optimized for analytical querying rather than transactional ticket updates. The next feature I would add is ticket assignment and an audit trail so the support team can track ownership and each status transition. Filters, validation, priorities, and live ticket statistics are already included as bonus functionality.

## Source package

`day-1-lakebase-support-app-submission.zip` contains the source code and captured evidence. It excludes `.env`, `node_modules/`, build artifacts, `.agents/`, and `.ai-dev-kit/`.
