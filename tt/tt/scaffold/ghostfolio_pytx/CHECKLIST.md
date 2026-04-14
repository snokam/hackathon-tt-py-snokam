# ROAI TS Import Audit

Every external import in `projects/ghostfolio/apps/api/src/app/portfolio/calculator/roai/portfolio-calculator.ts` is accounted for below. "Covered by" is the shim symbol that replaces it.

## Runtime symbols (need shim)

| TS import                                        | Module                       | Covered by (shim symbol)                               |
| ------------------------------------------------ | ---------------------------- | ------------------------------------------------------ |
| `PortfolioCalculator`                            | `@ghostfolio/api/.../portfolio-calculator` | `app.wrapper.portfolio.calculator.portfolio_calculator:PortfolioCalculator` |
| `getFactor`                                      | `@ghostfolio/api/helper/portfolio.helper` | `ghostfolio_helper._get_factor`                        |
| `getIntervalFromDateRange`                       | `@ghostfolio/common/calculation-helper` | `ghostfolio_helper._interval_from_range`               |
| `DATE_FORMAT`                                    | `@ghostfolio/common/helper`  | `ghostfolio_helper._DATE_FORMAT`                       |
| `Logger`                                         | `@nestjs/common`             | `nest_logger.Logger`                                   |
| `Big`                                            | `big.js`                     | `bigjs.Big` (+ `_big_to_fixed`)                        |
| `addMilliseconds`                                | `date-fns`                   | `datefns._add_milliseconds`                            |
| `differenceInDays`                               | `date-fns`                   | `datefns._difference_in_days`                          |
| `eachYearOfInterval`                             | `date-fns`                   | `datefns._each_year_of_interval`                       |
| `format`                                         | `date-fns`                   | `datefns._date_format`                                 |
| `isBefore`                                       | `date-fns`                   | `datefns._is_before`                                   |
| `isThisYear`                                     | `date-fns`                   | `datefns._is_this_year`                                |
| `cloneDeep`                                      | `lodash`                     | `lodashish.cloneDeep`                                  |
| `sortBy`                                         | `lodash`                     | `lodashish.sortBy`                                     |

## Type-only symbols (erased at preprocess step — no runtime shim)

| TS import                              | Module                                          |
| -------------------------------------- | ----------------------------------------------- |
| `PortfolioOrderItem`                   | `@ghostfolio/api/app/portfolio/interfaces/...`  |
| `AssetProfileIdentifier`, `SymbolMetrics` | `@ghostfolio/common/interfaces`              |
| `PortfolioSnapshot`, `TimelinePosition`| `@ghostfolio/common/models`                     |
| `DateRange`                            | `@ghostfolio/common/types`                      |
| `PerformanceCalculationType`           | `@ghostfolio/common/types/performance-calculation-type.type` |

Type-only imports are listed with `"python": null` in `tt_import_map.json` so the emitter knows to drop them.

## Big.js method coverage

All `Big` method calls the TS file uses are routed by `tt_import_map.json::methods`:

- Arithmetic:     `plus`, `minus`, `times`, `mul`, `div`, `abs`
- Conversion:     `toNumber`, `toFixed`, `toString`
- Predicate:      `isZero`, `isNeg`, `isPos`
- Comparison:     `eq`, `lt`, `gt`, `lte`, `gte`

## Global identifiers

`null`/`undefined` → `None`, `true`/`false` → `True`/`False`, `DATE_FORMAT` → `_DATE_FORMAT`.
