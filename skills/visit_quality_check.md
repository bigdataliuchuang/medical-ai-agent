# Skill: 就诊数据质量检查

## 适用场景
用户询问就诊数据的质量问题，包括：入院/出院时间逻辑异常、visit_id 重复、就诊无患者关联、就诊类型缺失等。
触发关键词：就诊质量、就诊数据、入院时间、出院时间、时间逻辑、visit_id、就诊关联。

## 业务口径

### 核心质量规则
| 规则编码 | 规则名称 | 检查逻辑 |
|----------|----------|----------|
| DQ-001 | 患者ID非空 | mpi_id IS NOT NULL |
| DQ-002 | 入院时间早于出院时间 | admit_date < discharge_date |
| DQ-003 | 住院天数合理 | DATEDIFF(discharge_date, admit_date) BETWEEN 0 AND 365 |
| DQ-004 | 就诊类型非空 | visit_type IS NOT NULL |
| DQ-005 | 科室编码合法 | dept_code 存在于 dim_dept_dict |

## 推荐使用表

| 表名 | 用途 |
|------|------|
| `dwd.dwd_visit` | 就诊明细，直接计算质量指标 |
| `dq.dq_check_result` | DQ规则结果 |
| `ads.ads_inpatient_quality_board` | 住院质量看板汇总 |
| `dim.dim_dept_dict` | 科室字典，验证合法性 |

## 常见 SQL 模板

### 模板1：入院时间晚于出院时间的异常记录数
```sql
SELECT
    COUNT(*) AS anomaly_cnt,
    COUNT(*) * 100.0 / (SELECT COUNT(*) FROM dwd.dwd_visit
                         WHERE visit_type='住院'
                           AND visit_date >= DATE_FORMAT(NOW(),'%Y-%m-01')) AS anomaly_rate
FROM dwd.dwd_visit
WHERE visit_type = '住院'
  AND admit_date >= discharge_date
  AND visit_date >= DATE_FORMAT(NOW(), '%Y-%m-01')
LIMIT 1;
```

### 模板2：无患者 mpi 关联的就诊记录数
```sql
SELECT
    DATE(visit_date) AS check_date,
    COUNT(*) AS total,
    SUM(CASE WHEN mpi_id IS NULL OR mpi_id = '' THEN 1 ELSE 0 END) AS no_mpi_cnt
FROM dwd.dwd_visit
WHERE visit_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
GROUP BY DATE(visit_date)
ORDER BY check_date
LIMIT 30;
```

### 模板3：住院质量看板（平均住院天数按科室）
```sql
SELECT
    dept_name,
    avg_inpatient_days,
    surgery_cnt,
    stat_month
FROM ads.ads_inpatient_quality_board
WHERE stat_month = DATE_FORMAT(NOW(), '%Y-%m')
ORDER BY avg_inpatient_days DESC
LIMIT 20;
```

## 数据质量风险
1. **时区导致的时间异常**：时间字段需确认是否为 UTC 或本地时间
2. **门诊无住院时间**：门诊记录不应有 admit_date/discharge_date，需按 visit_type 分类检查
3. **历史遗留问题**：历史数据质量差不代表现在有问题，建议按时间段拆分分析

## 示例问题
- 入院时间晚于出院时间的异常记录有多少
- 本月没有 mpi 关联的就诊记录数
- 各科室平均住院天数是多少
- 就诊数据整体质量评分如何
