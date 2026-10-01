## What changed

<!-- What did you change and why? Keep README and code comments user-facing; no internal process logs. -->

## User-visible changes

<!-- If CLI flags, config keys, brushing behaviour or docs changed, write one user-facing release note. Otherwise leave empty. -->

## Verification

- [ ] `make lint` (compile check + full offline unit tests)
- [ ] Behaviour changes come with an offline test under `tests/` (no network, no real account)
- [ ] Failure, skip and "platform has not confirmed" messages are still honest
- [ ] Any platform validation states its scope without publishing account details
- [ ] Unverified paths are clearly marked in the docs
- [ ] Commit messages use a Conventional Commit prefix (`feat:` / `fix:` / `docs:` / `test:` / `chore:`)

## Security and privacy

- [ ] No cookies, passwords, API keys, `config.ini`, `accounts/` or logs are committed
- [ ] New capture samples are sanitized (no token, no cookie)
- [ ] No forged study time, heartbeats or platform completion status
- [ ] Nothing "skipped" is recorded as "done"

## Related

<!-- Closes #xxx, if applicable -->
