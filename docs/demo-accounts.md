# Demo accounts

Made by [backend/scripts/seed_demo.py](../backend/scripts/seed_demo.py). They exist only where the script has
been run (so far, the local copy at http://localhost:3000).

**Password for every account:** `demo123456`

| Email | Account | Role | What it shows |
|---|---|---|---|
| maya.demo@example.com | Northwind | Owner | The full demo: team, API keys, 5 endpoints in different states, consumers and portal. Also a developer in Acme Analytics |
| alex.demo@example.com | Northwind | Admin | Admin view |
| priya.demo@example.com | Northwind | Developer | Developer view |
| sam.demo@example.com | Northwind | Viewer | Read-only view |
| jordan.demo@example.org | Acme Analytics | Owner | A smaller account |
| new.demo@example.net | (own) | Owner | A brand-new, empty account with the getting-started checklist |

## Creating them

From `backend/`:

```
python scripts/seed_demo.py           # create the accounts
python scripts/seed_demo.py --reset   # delete and recreate them fresh
```

On a public server, choose your own password, because the default above is in a public repository:

```
DEMO_PASSWORD=your-own-password python scripts/seed_demo.py
```
