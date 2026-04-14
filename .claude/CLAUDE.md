# TypeScript-to-Python Translation Competition Rules

## Competition Context

**Goal**: Build a Translation Tool (TT) that converts TypeScript to Python for the Ghostfolio financial portfolio management system.

**Time**: 3 hours of coding (15:30 – 18:30)
**Judging**: Correctness (85%), code quality (15%), understanding
**Deadline**: Final commit on main branch by 18:30

## Critical Rules - MUST FOLLOW

1. **NO LLMs for translation** - TT must not use LLMs to translate code. LLMs can only be used to build the TT itself.
2. **NO project-specific logic** - TT core (`tt/`) must contain no hard-coded project mappings (e.g., `@ghostfolio/...` imports). Project-specific config belongs in `tt_import_map.json`.
3. **NO node/js-tools** - Translation must happen in Python only. Cannot call external JS tools.
4. **NO wrapper modification** - Must copy wrapper from `translations/ghostfolio_pytx_example/` byte-for-byte. Only modify `app/implementation/`.
5. **Frequent commits** - Git log must show gradual development. Commit often.
6. **Python-only translation** - May use AST libraries in Python.

## Workflow

1. Develop/improve translator in `tt/`
2. Run `make evaluate_tt_ghostfolio` to translate and test
3. Run `make publish_results` to submit results to live dashboard
4. Analyze failures and iterate
5. Commit frequently with descriptive messages

## Scoring Breakdown

- **Correctness (85%)**: Number of API tests passed (weighted by difficulty)
- **Code Quality (15%)**: Readability, maintainability, DRY, pyscn metrics
- **Understanding**: Must be able to explain what TT does
- **Completion Time**: Tiebreaker if multiple teams solve same tests

## Code Quality Metrics

Run `make scoring_codequality` to check:
- health_score (0-100) with letter grade (A-F)
- complexity_score
- dead_code_score
- duplication_score
- coupling_score
- dependency_score
- architecture_score

## Rule Breach Detection

Run `make detect_rule_breaches` to verify:
- No LLM usage in tt/
- No direct project mappings in tt/ core
- No explicit implementation logic in tt/
- No financial logic in scaffold
- No code block copying from tt/ to output
- Wrapper files unchanged from example
- Interface compliance

## Solution Requirements

Must include by 18:30:
1. Runnable implementation of TT
2. `SOLUTION.md` explaining approach and strategy
3. All changes committed to main branch

## Project Layout

```
translations/ghostfolio_pytx/app/
├── main.py                    # immutable wrapper (copied from example)
├── wrapper/                   # immutable wrapper layer
└── implementation/            # TT-generated code (ONLY modify this)
```

## Commands to Remember

- `make evaluate_tt_ghostfolio` - Full evaluation (translate + test + score)
- `make translate-and-test-ghostfolio_pytx` - Quick translate and test
- `make publish_results` - Submit to competition dashboard
- `make detect_rule_breaches` - Check rule compliance
- `make scoring_codequality` - Check code quality metrics

## Best Practices

1. **Commit frequently** - Show gradual development
2. **Test often** - Run evaluate after each meaningful change
3. **Check rules** - Run breach detection before major commits
4. **Understand your code** - Be ready to explain TT strategy
5. **Focus on correctness** - 85% of score is tests passed
6. **Quality matters** - 15% is code quality, don't ignore it
7. **Time management** - 3 hours goes fast, prioritize high-impact changes

## Implementation Strategy

The scaffold already passes ~48 tests through basic cost-basis tracking. The failing tests require:
- Chart history with per-date market values
- Net performance (requires current prices)
- Gross performance from sells
- Time-weighted investment calculations
- Dividend/fee tracking

Focus translation effort on the `RoaiPortfolioCalculator` to bridge this gap.
