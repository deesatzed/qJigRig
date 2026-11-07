# Browser and role-client interpretation boundary

On 2026-11-07, two role-defined local clients and Chrome shared a loopback qJig service with a temporary catalog. A synthetic builder imported a 14-day refund source and saved an interpretation linked to exact source offsets. A separate reviewer client retrieved that interpretation. Chrome displayed the interpretation with its builder attribution and source quotation.

The reviewer then queried for `waiver`, which occurred only in the interpretation, using an authored phrase control. The request remained deferred and returned no source evidence. After the service restarted on the same catalog, Chrome again displayed the interpretation; keyboard activation opened the source, whose text contained the original 14-day passage and did not contain the interpretation's waiver assertion. The page had no horizontal overflow at 390 × 844.

The optional check is `tests/test_source_browser.py::test_browser_and_two_role_clients_keep_interpretation_separate_after_restart`. The first test attempt failed because a test variable shadowed its service-start function; renaming the variable resolved that harness error. The focused source-browser, role-client and claim suite then passed 10 tests.

Role labels are caller assertions, not authentication or independent review. This synthetic workflow does not establish semantic correctness, a complete review lifecycle, full browser/accessibility acceptance or hosted-provider behavior. No model call occurred.
