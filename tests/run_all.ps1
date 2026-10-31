Set-Location (Split-Path -Parent $PSScriptRoot)
$fail = 0
$tests = @("tests/test_memory.py","tests/test_memory_learn.py","tests/test_fastpath.py","tests/test_tools_guard.py","tests/test_call_routing.py","tests/test_call_connect.py","tests/test_turn_taking.py","tests/test_main_turns.py","tests/test_bridge_stale.py","tests/test_call_flow.py","tests/test_call_attach.py","tests/test_call_conversation.py","tests/test_new_features.py","tests/test_dashboard.py","tests/test_island.py")
foreach ($t in $tests) {
  Write-Host "== $t"
  & .\.venv\Scripts\python.exe $t
  if ($LASTEXITCODE -ne 0) { $fail = 1 }
}
if ($fail -eq 0) { Write-Host "ALL PASSED" } else { Write-Host "SOME TESTS FAILED"; exit 1 }
