# Security policy

Springform handles logins, sessions and stored credentials, so security reports are welcome.

## Supported versions

Until 1.0, only the latest release gets security fixes. Upgrade to it before reporting.

## Reporting a vulnerability

Use GitHub's private form: the **Security** tab of this repository, then **Report a
vulnerability**. Only the maintainer sees the report.

Do not open a public issue, discussion or pull request for anything exploitable.

Include what you found, how to reproduce it, the version or commit, and the impact you expect.

## What to expect

- An acknowledgement within a week.
- After that, a fix or a plan with a rough timeline.
- Credit in `CHANGELOG.md` when the fix ships, if you want it.

## Scope

- A `PREVIEW_MODE` install holds sample data only, and anyone who opens it can sign in as an
  admin. That is by design, not a vulnerability.
- A client fork is run by its own maintainer. Report a problem in a fork's own code to that
  maintainer; report a problem in Springform's core here.
