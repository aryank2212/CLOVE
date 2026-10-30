# Plan: rebrand CLOVE from one file

**Why.** CLOVE is offered as a template under a commercial licence. A buyer wants their own name, wake word,
colours and voice without hunting through Python, TypeScript and Rust.

**What.**
- A `brand.toml` at the top of the repository: product name, wake word and its spellings, accent colour, voice,
  icon and wordmark files.
- The assistant reads it at start (name in the prompt and window, wake word aliases, voice); Clove Notch reads it
  at build time (window title, accent, icon, sounds folder).
- A `docs/TEMPLATE.md` guide: what can be changed, what the AGPL and commercial licences each allow, and a
  checklist before selling or shipping.
- A test that builds with a sample brand and checks no "CLOVE" text is left in what a person sees.

**Done when.** Changing `brand.toml` to "Nova" with a blue accent gives an assistant that answers to "Nova", a
notch titled Nova, and blue buttons, with no code edits.
