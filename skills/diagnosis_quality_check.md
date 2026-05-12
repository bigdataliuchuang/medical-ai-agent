# Skill: 诊断数据质量检查

## 适用场景
用户询问诊断数据的质量问题，包括：诊断编码缺失、ICD-10 映射失败、主诊断为空、诊断与就诊不关联等。
触发关键词：诊断编码、ICD-10、诊断缺失、诊断质量、主诊断、诊断映射。

## 输入参数
- 时间范围（建议提供）：check_date / stat_date
- 严重等级（可选）：HIGH / MEDIUM / LOW
- 目标表（可选）：dwd_diagnosis 或具体来源系统

## 业务口径

### 诊断编码质量规则（对应 DQ 规则目录）
| 规则编码 | 规则名称 | 检查逻辑 |
|----------|----------|----------|
| DQ-010 | 诊断编码非空检查 | diagnosis_code IS NOT NULL AND diagnosis_code != '' |
| DQ-011 | ICD-10格式校验 | diagnosis_code REGEXP '^[A-Z][0-9]{2}' |
| DQ-012 | 主诊断非空检查 | diagnosis_type='主诊断' AND diagnosis_code IS NOT NULL |
| DQ-013 | 诊断字典映射检查 | 存在于 dim_diagnosis_dict 中 |
| DQ-014 | 诊断就诊关联检查 | visit_id 在 dwd_visit 中存在 |

### 严重等级定义
- HIGH：主诊断为空、诊断编码完全缺失
- MEDIUM：ICD-10 格式不合规、字典映射失败
- LOW：次要诊断缺失、编码不规范

## 推荐使用表

| 表名 | 用途 |
|------|------|
| `ads.ads_dq_result_summary` | DQ评分汇总，按数据层聚合 |
| `dq.dq_check_result` | 各规则检查结果，含通过/失败数 |
| `dq.dq_issue_detail` | 问题明细，含具体违规记录 |
| `dwd.dwd_diagnosis` | 诊断明细，用于直接计算 |
| `dim.dim_diagnosis_dict` | ICD-10 字典，用于映射验证 |

## 执行步骤

1. **确认检查范围**：时间范围 + 严重等级
2. **优先查 DQ 汇总表**：从 ads_dq_result_summary 获取整体评分
3. **规则粒度分析**：从 dq_check_result 获取各规则的通过/失败数
4. **问题明细下钻**：如需具体违规记录，查 dq_issue_detail
5. **直接计算（可选）**：从 dwd_diagnosis 直接统计，用于验证 DQ 结果
6. **输出**：问题数量、占比、建议修复优先级

## 常见 SQL 模板

### 模板1：本周诊断相关 DQ 问题汇总
```sql
SELECT
    rule_name,
    severity_level,
    fail_count,
    total_count,
    ROUND(fail_count * 100.0 / NULLIF(total_count, 0), 2) AS fail_rate
FROM dq.dq_check_result
WHERE rule_code LIKE 'DQ-01%'
  AND check_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
ORDER BY severity_level DESC, fail_count DESC
LIMIT 20;
```

### 模板2：诊断编码为空的记录数（直接计算）
```sql
SELECT
    DATE(visit_date) AS check_date,
    COUNT(*) AS total_records,
    SUM(CASE WHEN diagnosis_code IS NULL OR diagnosis_code = '' THEN 1 ELSE 0 END) AS null_cnt,
    ROUND(SUM(CASE WHEN diagnosis_code IS NULL OR diagnosis_code = '' THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 2) AS null_rate
FROM dwd.dwd_diagnosis
WHERE visit_date >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
GROUP BY DATE(visit_date)
ORDER BY check_date
LIMIT 30;
```

### 模板3：映射失败的诊断编码 TOP 10
```sql
SELECT
    d.diagnosis_code,
    COUNT(*) AS fail_cnt
FROM dwd.dwd_diagnosis d
LEFT JOIN dim.dim_diagnosis_dict dd ON d.diagnosis_code = dd.icd_code
WHERE dd.icd_code IS NULL
  AND d.visit_date >= DATE_FORMAT(NOW(), '%Y-%m-01')
GROUP BY d.diagnosis_code
ORDER BY fail_cnt DESC
LIMIT 10;
```

## 数据质量风险

1. **DQ 结果滞后**：DQ 检查通常 T+1，实时性问题需直接查 dwd 表
2. **历史数据污染**：存量数据质量差不代表当前新增数据有问题，需区分时间段
3. **多来源系统**：HIS / EMR / LIS 等不同来源系统的诊断编码格式可能不同
4. **编码版本**：ICD-10 存在 2010 版和 2016 版，需确认院内使用版本

## 示例问题
- 本周诊断数据质量最差的规则是哪些
- 诊断编码为空的记录数量
- ICD-10 映射失败的诊断编码有哪些
- 主诊断为空影响哪些科室
- HIGH 严重等级的 DQ 问题有多少条
