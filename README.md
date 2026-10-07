# HackWave — Hackathon Management Application

A runnable **Python standard-library + SQLite + vanilla JavaScript** full-stack application. No npm, pip, or external database required for the local demo.

## Start

```bash
cd hackwave
python3 server.py
```

Open **http://127.0.0.1:8000** in a browser. To serve on your network, set `HOST=0.0.0.0` (only on a trusted network).

### Demo accounts

- Admin: `admin@hackwave.local`
- Reviewers: `judge1@hackwave.local` to `judge5@hackwave.local`
- Team lead: `team1@hackwave.local` to `team7@hackwave.local`
- Default demo password for all: `Demo@12345`

Override the seed password **before initial database creation** with `HACKWAVE_DEMO_PASSWORD`. Delete `hackwave.db` to reset demo data (deletes all registrations/scores).

## Features implemented

- Public mobile-responsive landing page, server-based 24-hour countdown, schedule, challenge statements and conditional leaderboard.
- Register new team leader with hashed password and persisted SQLite team registration.
- Login sessions with HttpOnly cookies, CSRF token for authenticated actions, role-based access checks.
- Admin view and approve/reject teams, edit event dates, add sessions, publish/unpublish scores.
- Each of five seeded reviewers can independently score assigned teams across three rounds; scores are validated, locked and stored in SQLite.
- Team dashboard and per-problem rankings; 20/30/50 weighted overall scores appear only after all five assigned judges complete every round.
- Responsive layouts, auto-refresh every 30 seconds.

## Important scope limits

This is a **working local MVP**, not production-ready software. It is deliberately dependency-free and uses SQLite instead of the originally proposed Next.js/Supabase stack. Reviewer assignments are seeded for all teams; newly registered teams currently need assignments added by an administrator directly in SQLite, before reviewers can score them. There are no member invitations, email notifications, judge reassignment UI, audit report UI, schedule editing, competition-grade anti-abuse throttling, TLS setup or cloud deployment pipeline. Configure a real domain, HTTPS reverse proxy, safe backups, email verification, hardened security/rate limits, and an appropriate hosted database before public internet deployment. Do not expose the included demo accounts/passwords publicly.

## Scoring rules

Each evaluation is out of 100: Innovation 20, Technical 25, Relevance 20, Prototype 20, Presentation 15. Review rounds are weighted 20%, 30%, 50%. Every seeded approved team has five reviewer assignments for each of the three rounds. Team leaderboard score is published only after all required evaluations have been submitted across all three rounds; incomplete reviews display Pending. Public leaderboard visibility is controlled by admins.

## Environment

`HOST` (default `127.0.0.1`), `PORT` (default `8000`), `HACKWAVE_DB` (default `hackwave.db`), `HACKWAVE_DEMO_PASSWORD` (default `Demo@12345`). Python 3.10 or higher is recommended.
