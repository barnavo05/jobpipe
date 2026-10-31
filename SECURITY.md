# Security policy

## Reporting a vulnerability

Please don't open a public issue for security problems.

Use **Security > Report a vulnerability** on this repo to report it privately. I'll reply within a few days.

Useful to include: what you found, steps to reproduce, and what someone could do with it.

## What's in scope

- The Telegram bot (@jobpipe_alerts_bot) and how it handles user data
- The code in this repository, the GitHub Actions workflows and the Vercel app

## How secrets are handled

Bot token and database URL live only in GitHub Secrets and Vercel environment variables, never in this repo. See the Security section in README.md.
