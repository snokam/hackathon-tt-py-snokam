Quick translate and test cycle without publishing:

1. Run TT translator to generate Python code
2. Run API test suite against translated code
3. Show test results

This is faster than full evaluation when you want quick feedback without quality scoring or publishing.

Execute: `make translate-and-test-ghostfolio_pytx`

Use this for rapid iteration when developing translator improvements.
