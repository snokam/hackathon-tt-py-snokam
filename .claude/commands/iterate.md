Run the full competition workflow cycle:

1. Translate TypeScript to Python using current TT implementation
2. Run full test suite against translated code
3. Run code quality scoring
4. Run rule breach detection
5. Publish results to competition dashboard
6. Show summary of results with test pass rate and any rule violations

This is the main iteration command for the competition. Use after making changes to the translator.

Execute: `make evaluate_tt_ghostfolio && make publish_results`

After execution, analyze the results and suggest specific improvements to increase test pass rate.
