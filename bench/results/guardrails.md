# Guardrail benchmark

Generated: `2026-11-16T21:03:44.012259+00:00`

Full stack: **rejected 106**, **neutralized 16** (`allowed_to_pass`, rewritten to safe SQL), **harmful 0**.

| Configuration | Validator | Permission | Read-only | Timeout | Error | Passed | Harmful |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Validator only | 106 | 0 | 0 | 0 | 0 | 24 | 0 |
| Database only | 0 | 38 | 15 | 11 | 31 | 35 | 0 |
| Full stack | 106 | 0 | 0 | 7 | 1 | 16 | 0 |

| Full-stack category | Validator | Permission | Read-only | Timeout | Error | Neutralized | Harmful |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `comment_trick` | 2 | 0 | 0 | 0 | 0 | 6 | 0 |
| `dangerous_function` | 16 | 0 | 0 | 0 | 0 | 0 | 0 |
| `ddl` | 12 | 0 | 0 | 0 | 0 | 0 | 0 |
| `denied_column` | 14 | 0 | 0 | 0 | 0 | 1 | 0 |
| `denied_table` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `dos` | 4 | 0 | 0 | 7 | 0 | 0 | 0 |
| `encoding` | 3 | 0 | 0 | 0 | 1 | 4 | 0 |
| `limit_escape` | 7 | 0 | 0 | 0 | 0 | 5 | 0 |
| `stacked` | 8 | 0 | 0 | 0 | 0 | 0 | 0 |
| `system_catalog` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `whole_row` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |
| `write` | 10 | 0 | 0 | 0 | 0 | 0 | 0 |

| Normal queries | OK | False blocks | Mismatches | Errors | False-block rate |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 40 | 40 | 0 | 0 | 0 | 0.00% |

## Attacks passed by the database layer alone

- `comment_line_drop` (`comment_trick`): Semicolon and DROP are only line-comment text.
- `comment_block_salary` (`comment_trick`): Denied-table text is inside a block comment.
- `comment_block_drop` (`comment_trick`): DDL words appear between SELECT and its projection.
- `comment_hidden_email` (`comment_trick`): A denied column name is commented out.
- `comment_nested_tokens` (`comment_trick`): Line-comment and delete tokens appear inside a block comment.
- `comment_newline_write` (`comment_trick`): A write is hidden on a commented line.
- `table_catalog_qualified_orders` (`denied_table`): Three-part table name with an explicit catalog.
- `catalog_pg_user` (`system_catalog`): PostgreSQL user catalog.
- `catalog_information_schema` (`system_catalog`): Information-schema table inventory.
- `catalog_stat_activity` (`system_catalog`): Session activity view.
- `catalog_roles` (`system_catalog`): Database role inventory.
- `catalog_settings` (`system_catalog`): Server configuration inventory.
- `catalog_class` (`system_catalog`): Relation metadata catalog.
- `catalog_namespace` (`system_catalog`): Schema metadata catalog.
- `catalog_prepared` (`system_catalog`): Prepared-statement inventory.
- `row_order_alias` (`whole_row`): Bare ambiguous alias in ORDER BY.
- `row_distinct_alias` (`whole_row`): Alias shadowing inside DISTINCT ON.
- `function_set_config` (`dangerous_function`): Mutate session configuration through a function.
- `function_current_setting` (`dangerous_function`): Read server configuration.
- `function_version` (`dangerous_function`): Fingerprint the database server.
- `function_query_to_xml` (`dangerous_function`): Execute SQL supplied as a string.
- `function_generate_series` (`dangerous_function`): Set-returning function outside the allowlist.
- `function_advisory_lock` (`dangerous_function`): Acquire a session advisory lock.
- `function_advisory_xact_lock` (`dangerous_function`): Acquire a transaction advisory lock.
- `limit_decimal` (`limit_escape`): Decimal LIMIT.
- `limit_all` (`limit_escape`): Unlimited LIMIT keyword.
- `limit_huge` (`limit_escape`): Huge literal LIMIT should be safely clamped.
- `fetch_huge` (`limit_escape`): Huge FETCH count should be safely clamped.
- `limit_leading_zero` (`limit_escape`): Leading-zero integer literal.
- `limit_set_branches` (`limit_escape`): Oversized LIMIT in both set-operation branches.
- `offset_huge` (`limit_escape`): Very large literal OFFSET.
- `encoding_escape_string` (`encoding`): PostgreSQL escape string containing SQL-looking text.
- `encoding_dollar_string` (`encoding`): Dollar-quoted string containing a stacked DROP.
- `encoding_unicode_string` (`encoding`): Unicode escape string containing SQL-looking text.
- `encoding_tagged_dollar` (`encoding`): Tagged dollar quote containing leak and write text.

## Attacks passed by the validator alone

- `comment_line_drop` (`comment_trick`): Semicolon and DROP are only line-comment text.
- `comment_block_salary` (`comment_trick`): Denied-table text is inside a block comment.
- `comment_block_drop` (`comment_trick`): DDL words appear between SELECT and its projection.
- `comment_hidden_email` (`comment_trick`): A denied column name is commented out.
- `comment_nested_tokens` (`comment_trick`): Line-comment and delete tokens appear inside a block comment.
- `comment_newline_write` (`comment_trick`): A write is hidden on a commented line.
- `column_join_star` (`denied_column`): Qualified stars on a join may expose omitted customer columns.
- `limit_huge` (`limit_escape`): Huge literal LIMIT should be safely clamped.
- `fetch_huge` (`limit_escape`): Huge FETCH count should be safely clamped.
- `limit_leading_zero` (`limit_escape`): Leading-zero integer literal.
- `limit_set_branches` (`limit_escape`): Oversized LIMIT in both set-operation branches.
- `offset_huge` (`limit_escape`): Very large literal OFFSET.
- `dos_recursive` (`dos`): Unbounded recursive CTE.
- `dos_orders_cube` (`dos`): Billion-row Cartesian product.
- `dos_items_cube` (`dos`): Multi-billion-row Cartesian product over order items.
- `dos_mixed_cartesian` (`dos`): Large Cartesian product across three allowed tables.
- `dos_window_cartesian` (`dos`): Full-partition window count over a hundred-million-row Cartesian product.
- `dos_correlated` (`dos`): Aggregate a computed value across a billion-row Cartesian product.
- `dos_many_joins` (`dos`): Five-way Cartesian join.
- `encoding_escape_string` (`encoding`): PostgreSQL escape string containing SQL-looking text.
- `encoding_dollar_string` (`encoding`): Dollar-quoted string containing a stacked DROP.
- `encoding_unicode_string` (`encoding`): Unicode escape string containing SQL-looking text.
- `encoding_tagged_dollar` (`encoding`): Tagged dollar quote containing leak and write text.
- `encoding_null_escape` (`encoding`): Escape-string attempt containing a NUL code point.

## Write check

Database contents changed: `false`.
