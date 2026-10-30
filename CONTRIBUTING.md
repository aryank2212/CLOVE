# Contributing

Thanks for helping. Before you start:

- **Licence of contributions**: CLOVE is dual-licensed (AGPL-3.0 and commercial). By opening a pull request you
  agree that your contribution may be distributed under both, and you confirm you have the right to give it.
  Changes to `notch/` stay MIT.
- **Keep changes small** and focused on one thing, with a test when behaviour changes.
- **Run the tests** before sending:
  ```bash
  cd assistant && tests/run_all.sh          # the assistant (some timing checks are sensitive to load)
  cd notch && npm test && npx tsc --noEmit  # Clove Notch
  ```
- **Follow the look** in [docs/DESIGN.md](docs/DESIGN.md), and the wording rules there: say what happened and what
  to do next, never invent data.
- **Never commit secrets**: `.env` files, tokens and personal data stay out of the repository.
