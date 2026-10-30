# Plan: steady timing tests under load

**Why.** Two assistant tests measure real time and fail when the PC is busy, though nothing is broken:
- `test_main_turns.py`: a short command must end within about 1 s; it took 1.1 to 1.4 s while Clove Notch was
  open and animating.
- `test_turn_taking.py`: fails while Clove Notch's window is visible, passes once it is hidden.

A test that fails for no reason teaches people to ignore red tests, which is how real breakage slips through.

**What.**
- Measure what the test is about (how long the end-of-sentence check waits) with a fake clock, instead of the
  wall clock of the whole PC.
- Keep one real-time check, with a margin, behind a `CLOVE_TIMING=1` switch for benchmarking.

**Done when.** Both tests pass ten runs in a row with Clove Notch open and animating, and still fail if the wait
is made longer on purpose.
