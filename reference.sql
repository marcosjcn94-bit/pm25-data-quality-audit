-- SQLite computes the coverage, estimates and contrasts from daily records.
CREATE VIEW reference_monitor_months AS
WITH RECURSIVE calendar(month_start) AS (
    SELECT '2024-01-01'
    UNION ALL
    SELECT date(month_start, '+1 month') FROM calendar WHERE month_start < '2024-12-01'
),
monitors(site, poc) AS (
    VALUES ('1103','3'), ('1302','3'), ('4009','3'), ('9035','1')
),
counts AS (
    SELECT monitors.site, monitors.poc, substr(month_start, 1, 7) AS month,
           CAST(strftime('%d', date(month_start, '+1 month', '-1 day')) AS INTEGER)
               AS calendar_days,
           COUNT(daily.date) AS source_days,
           COUNT(CASE WHEN daily.hours >= 18 AND daily.mean IS NOT NULL THEN 1 END)
               AS valid_days,
           AVG(CASE WHEN daily.hours >= 18 THEN daily.mean END) AS monitor_mean,
           SUM(CASE WHEN daily.hours >= 18 THEN daily.mean END) AS valid_sum
    FROM monitors CROSS JOIN calendar
    LEFT JOIN daily ON daily.site = monitors.site AND daily.poc = monitors.poc
                    AND daily.date >= month_start AND daily.date < date(month_start, '+1 month')
    GROUP BY monitors.site, monitors.poc, month_start
)
SELECT *, 1.0 * valid_days / calendar_days AS coverage,
       valid_days >= 1 AS eligible_any,
       4 * valid_days >= 3 * calendar_days AS eligible_75,
       10 * valid_days >= 9 * calendar_days AS eligible_90
FROM counts;

CREATE VIEW reference_monthly AS
WITH rules(rule) AS (VALUES ('any'), ('75'), ('90')),
eligible AS (
    SELECT mm.*, rules.rule,
           CASE rules.rule
               WHEN 'any' THEN eligible_any
               WHEN '75' THEN eligible_75
               WHEN '90' THEN eligible_90
           END AS include
    FROM reference_monitor_months AS mm CROSS JOIN rules
),
estimates AS (
    SELECT month, rule, SUM(include) AS eligible_count,
           COALESCE(group_concat(CASE WHEN include THEN site || '/' || poc END, ';'), '')
               AS eligible_ids,
           SUM(CASE WHEN include THEN valid_days ELSE 0 END) AS valid_monitor_days,
           AVG(CASE WHEN include THEN monitor_mean END) AS equal_monitor_mean,
           SUM(CASE WHEN include THEN valid_sum END)
               / NULLIF(SUM(CASE WHEN include THEN valid_days ELSE 0 END), 0) AS equal_day_mean
    FROM (SELECT * FROM eligible ORDER BY month, rule, site, poc)
    GROUP BY month, rule
)
SELECT *, equal_monitor_mean - equal_day_mean AS difference
FROM estimates;

CREATE VIEW reference_audit AS
WITH contrasts AS (
    SELECT month, 'weights_' || rule AS contrast, 'equal_monitor_minus_equal_day' AS weight,
           equal_day_mean AS baseline, equal_monitor_mean AS comparison
    FROM reference_monthly
    UNION ALL
    SELECT first.month, second.rule || '_minus_' || first.rule, 'equal_monitor',
           first.equal_monitor_mean, second.equal_monitor_mean
    FROM reference_monthly AS first JOIN reference_monthly AS second USING (month)
    WHERE first.rule = 'any' AND second.rule IN ('75', '90')
       OR first.rule = '75' AND second.rule = '90'
    UNION ALL
    SELECT first.month, second.rule || '_minus_' || first.rule, 'equal_day',
           first.equal_day_mean, second.equal_day_mean
    FROM reference_monthly AS first JOIN reference_monthly AS second USING (month)
    WHERE first.rule = 'any' AND second.rule IN ('75', '90')
       OR first.rule = '75' AND second.rule = '90'
)
SELECT *, comparison - baseline AS difference FROM contrasts;
