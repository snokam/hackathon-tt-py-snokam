# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

# TypeScript-to-Python Translation Competition

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

---

# Architecture & Development Guide

## Repository Structure

```
hackathon-tt-py/
├── tt/                                  # Translation tool (YOUR CODE)
│   ├── tt/
│   │   ├── translator.py               # Core translation logic
│   │   ├── cli.py                      # Command-line interface
│   │   └── scaffold/ghostfolio_pytx/   # Support modules overlaid on output
│   └── pyproject.toml                  # TT dependencies (pytest, requests)
│
├── projects/ghostfolio/                # TypeScript source to translate
│   └── apps/api/src/app/portfolio/
│       └── calculator/roai/
│           └── portfolio-calculator.ts # Main file to translate
│
├── translations/
│   ├── ghostfolio_pytx_example/        # Reference scaffold (immutable)
│   │   └── app/
│   │       ├── main.py                 # FastAPI entry point
│   │       ├── wrapper/                # HTTP layer (DO NOT MODIFY)
│   │       └── implementation/         # Stub calculator
│   │
│   └── ghostfolio_pytx/                # TT output (auto-generated)
│       └── app/
│           ├── main.py                 # Copied from example
│           ├── wrapper/                # Copied from example
│           └── implementation/         # TT-generated code
│
├── projecttests/ghostfolio_api/        # API test suite (135 tests)
├── evaluate/                           # Scoring and rule checks
└── helptools/                          # Scaffold setup utilities
```

## Translation Pipeline

### How `tt translate` works:

1. **Scaffold Setup** (`helptools/setup_ghostfolio_scaffold_for_tt.py`)
   - Copy `translations/ghostfolio_pytx_example/` → `translations/ghostfolio_pytx/`
   - Overlay support modules from `tt/tt/scaffold/ghostfolio_pytx/`
   - Ensure all `__init__.py` files exist

2. **Translation** (`tt/tt/translator.py::run_translation`)
   - Read TypeScript source: `projects/ghostfolio/.../portfolio-calculator.ts`
   - Apply regex-based transformations (class declarations, methods, etc.)
   - Write to: `translations/ghostfolio_pytx/app/implementation/.../portfolio_calculator.py`

3. **Output Structure**
   - `app/main.py` — FastAPI entry point (copied byte-for-byte)
   - `app/wrapper/` — HTTP controllers, services, interfaces (immutable)
   - `app/implementation/` — Translated calculator (ONLY this is generated by TT)

## Wrapper vs Implementation Architecture

**Wrapper** (immutable, copied from example):
- `app/main.py` — FastAPI app initialization
- `app/wrapper/portfolio/portfolio_controller.py` — HTTP endpoints
- `app/wrapper/portfolio/portfolio_service.py` — Thin delegation layer
- `app/wrapper/portfolio/calculator/portfolio_calculator.py` — Abstract base class
- `app/wrapper/portfolio/current_rate_service.py` — Market price lookups

**Implementation** (TT-generated):
- `app/implementation/portfolio/calculator/roai/portfolio_calculator.py`
  - Must inherit from `PortfolioCalculator` (wrapper base class)
  - Must implement 6 abstract methods:
    - `get_performance()` → `{chart, firstOrderDate, performance}`
    - `get_investments(group_by)` → `{investments: [{date, investment}]}`
    - `get_holdings()` → `{holdings: {symbol: {...}}}`
    - `get_details(base_currency)` → `{accounts, holdings, summary}`
    - `get_dividends(group_by)` → `{dividends: [{date, investment}]}`
    - `evaluate_report()` → `{xRay: {categories, statistics}}`

## Current TT Implementation

The minimal `tt/tt/translator.py` uses **regex-based transformations**:

```python
# Removes TypeScript imports
re.sub(r'^import\s+.*?;?\s*$', '', python_code, flags=re.MULTILINE)

# Translates classes: class Name extends Base { → class Name(Base):
re.sub(r'export\s+class\s+(\w+)\s+extends\s+(\w+)\s*\{', r'class \1(\2):', ...)

# Translates methods: protected methodName() { → def methodName(self):
re.sub(r'(protected|private|public)?\s*(\w+)\s*\([^)]*\)\s*\{', ...)

# Translates return statements: return Enum.VALUE; → return "VALUE"
re.sub(r'return\s+(\w+)\.(\w+);', r'return "\2"', ...)

# Removes closing braces
re.sub(r'^\s*\}\s*$', '', python_code, flags=re.MULTILINE)
```

**Key limitation**: Only translates `getPerformanceCalculationType()` method. The rest remains stub code.

## Development Workflow

### Essential Commands

```bash
# Full evaluation cycle (translate + test + score + checks)
make evaluate_tt_ghostfolio

# Quick iteration (translate + test only)
make translate-and-test-ghostfolio_pytx

# Translate only
uv run --project tt tt translate

# Run tests against existing translation
make spinup-and-test-ghostfolio_pytx

# Check code quality
make scoring_codequality

# Verify rule compliance
make detect_rule_breaches

# Publish to competition dashboard
make publish_results
```

### Single Test Development

```bash
# Start the server manually
cd translations/ghostfolio_pytx
uv run uvicorn app.main:app --port 3335

# In another terminal, run specific test
GHOSTFOLIO_API_URL=http://localhost:3335 \
  uv run --project tt pytest projecttests/ghostfolio_api/test_advanced.py::test_open_position_current_value_in_base_currency -v

# Or run entire test file
GHOSTFOLIO_API_URL=http://localhost:3335 \
  uv run --project tt pytest projecttests/ghostfolio_api/test_btcusd.py -v
```

### Debugging Translation Output

```bash
# View translated Python code
cat translations/ghostfolio_pytx/app/implementation/portfolio/calculator/roai/portfolio_calculator.py

# Compare with TypeScript source
cat projects/ghostfolio/apps/api/src/app/portfolio/calculator/roai/portfolio-calculator.ts

# Check what scaffold provides
cat translations/ghostfolio_pytx_example/app/implementation/portfolio/calculator/roai/portfolio_calculator.py
```

## Test Suite Structure

**135 total tests**, organized by scenario:

- `test_advanced.py` — Open positions, net performance, chart entries
- `test_btcusd.py` — Chart history, holdings values, investment tracking
- `test_deeper.py` — Closed positions, dividends, performance metrics
- `test_details.py` — Holdings details, market prices
- `test_dividends.py` — Dividend tracking and grouping
- `test_novn_buy_and_sell.py` — Closed position calculations
- `test_remaining_specs.py` — Various symbol-specific scenarios
- `test_report.py` — Portfolio X-ray reports
- `test_same_day_transactions.py` — Same-day buy/sell
- `test_short_cover.py` — Short positions and covering

**Current baseline**: 48 passed, 87 failed

**Passing tests** rely on scaffold's cost-basis tracking in wrapper endpoints.

**Failing tests** require actual translated calculator logic (chart history, net performance, market value calculations).

## Improving the Translator

### Strategy for Increasing Test Pass Rate

1. **Parse more TypeScript constructs**
   - Constructor parameters
   - Private/protected fields
   - Method parameters with types
   - Complex return statements
   - Conditional logic (if/else/switch)
   - Loops (for, while)
   - Object/array destructuring

2. **Handle financial domain logic**
   - Date arithmetic
   - Decimal/precision calculations
   - Portfolio position tracking
   - Performance calculations (TWR, net/gross)
   - Currency conversions

3. **Use AST parsing** (allowed by rules)
   - Consider using Python AST libraries for TypeScript
   - More robust than regex for complex code
   - Examples: `ts2python`, custom tree-sitter parser

4. **Incremental approach**
   - Translate one method at a time
   - Test after each improvement
   - Commit frequently (required by rules)
   - Focus on methods that unlock the most tests

### Critical Methods to Translate

From `portfolio-calculator.ts`, in priority order:

1. `getPerformance()` — Unlocks chart and performance tests
2. `getHoldings()` — Unlocks holdings and market price tests
3. `getInvestments()` — Unlocks investment grouping tests
4. `getDividends()` — Unlocks dividend tests
5. `getDetails()` — Unlocks detail endpoint tests
6. `evaluate_report()` — Unlocks report tests

## Rule Compliance

**Automated checks** (`make detect_rule_breaches`):

- ✅ No LLM API calls in `tt/`
- ✅ No hardcoded `@ghostfolio/` imports in `tt/`
- ✅ No pre-written financial logic in `tt/`
- ✅ Wrapper files unchanged from example
- ✅ No verbatim code copying from `tt/` to output
- ✅ Calculator implements required interface

**Manual verification**:
- Git log shows gradual commits
- Can explain translation strategy to judges
- SOLUTION.md documents approach

## Testing Philosophy

**FastAPI health check**: `GET /api/v1/health` → `{"status": "ok"}`

**Test execution flow**:
1. Spin up FastAPI server on port 3335
2. Wait for health check to pass
3. Run pytest against `http://localhost:3335`
4. Tests call endpoints like `/api/v1/portfolio/performance`
5. Wrapper delegates to your translated calculator
6. Test assertions verify response structure and values

**Common test patterns**:
```python
# Performance endpoint
response = client.get_performance()
assert response["performance"]["totalInvestment"] == pytest.approx(expected, rel=1e-4)

# Holdings endpoint
holdings = client.get_holdings()["holdings"]
assert "AAPL" in holdings
assert holdings["AAPL"]["quantity"] == pytest.approx(10.0)

# Chart data
chart = client.get_performance()["chart"]
assert len(chart) > 0
assert chart[0]["netPerformance"] == pytest.approx(0.0)
```
