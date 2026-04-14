Check competition rule compliance:

Run automated rule breach detection and report any violations.

Execute: `make detect_rule_breaches`

The following checks are performed:
- detect_llm_usage: No LLM API calls in tt/
- detect_direct_mappings: No project-specific imports in tt/ core
- detect_explicit_implementation: No domain logic in tt/
- detect_explicit_financial_logic: No financial arithmetic in scaffold
- detect_scaffold_bloat: No extra helpers in scaffold
- detect_code_block_copying: No verbatim copying from tt/ to output
- detect_interface_violation: Calculator interface compliance
- detect_wrapper_modification: Wrapper files unchanged

Report any violations found and suggest fixes.
