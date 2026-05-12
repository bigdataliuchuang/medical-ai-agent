# Skill: 患者人数统计

## 适用场景
用户询问患者数量相关问题，包括：住院患者数、门诊患者数、新患者数、复诊患者数、按病种/科室/月份的患者分布。
触发关键词：患者数、患者人数、就诊人次、住院人次、门诊人次、患者统计、人数。

## 输入参数
- 时间范围（必填）：visit_date / stat_month
- 就诊类型（可选）：住院 / 门诊 / 急诊（visit_type）
- 病种（可选）：diagnosis_code / tumor_type
- 科室（可选）：dept_code / dept_name
- 统计粒度（可选）：按日 / 按月 / 按科室 / 按病种

## 业务口径

### 患者数 vs 就诊次数
| 指标 | 口径 | SQL |
|------|------|-----|
| 患者数（去重） | 同一患者多次就诊只算一次 | COUNT(DISTINCT mpi_id) |
| 就诊人次 | 每次就诊算一次 | COUNT(DISTINCT visit_id) |
| 住院人次 | 每次住院算一次 | COUNT(DISTINCT visit_id) WHERE visit_type='住院' |

**重要**：默认"患者数"应使用 COUNT(DISTINCT mpi_id)；"人次"使用 COUNT(DISTINCT visit_id)。

### 新患者定义
首次在本院就诊的患者，即 mpi_id 在目标时间段之前无记录。

### 复诊患者定义
在目标时间段内有至少 2 次就诊记录的患者。

## 推荐使用表

| 优先级 | 表名 | 用途 |
|--------|------|------|
| 首选 | `ads.ads_patient_mpi_summary` | 患者MPI汇总，已聚合 |
| 首选 | `ads.ads_tumor_report_monthly` | 肿瘤患者月报，含病种分布 |
| 明细 | `dwd.dwd_visit` | 就诊明细，支持任意维度聚合 |
| 明细 | `dwd.dwd_diagnosis` | 诊断明细，支持按病种过滤 |
| 字典 | `dim.dim_dept_dict` | 科室信息 |

## 执行步骤

1. **确认统计口径**：患者数（distinct mpi_id）还是就诊人次（distinct visit_id）
2. **确认就诊类型**：住院 / 门诊 / 急诊 / 全部
3. **确认时间范围**：精确到月还是到日
4. **选择表**：汇总直接用 ads/dws 表；按病种需关联 dwd_diagnosis
5. **确认分组维度**：按科室、按月、按病种还是汇总
6. **检查 mpi 覆盖率**：mpi_id 为空的记录会导致去重不准

## 常见 SQL 模板

### 模板1：本月住院患者数（按科室）
```sql
SELECT
    d.dept_name,
    COUNT(DISTINCT v.mpi_id) AS patient_cnt,
    COUNT(DISTINCT v.visit_id) AS visit_cnt
FROM dwd.dwd_visit v
JOIN dim.dim_dept_dict d ON v.dept_code = d.dept_code
WHERE v.visit_type = '住院'
  AND DATE_FORMAT(v.visit_date, '%Y-%m') = DATE_FORMAT(NOW(), '%Y-%m')
GROUP BY d.dept_name
ORDER BY patient_cnt DESC
LIMIT 20;
```

### 模板2：各月住院患者数趋势
```sql
SELECT
    report_month,
    patient_cnt,
    adr_rate
FROM ads.ads_tumor_report_monthly
WHERE report_month >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 6 MONTH), '%Y-%m')
ORDER BY report_month
LIMIT 12;
```

### 模板3：肺癌患者住院人次
```sql
SELECT
    COUNT(DISTINCT v.visit_id) AS inpatient_cnt,
    COUNT(DISTINCT v.mpi_id)   AS patient_cnt
FROM dwd.dwd_visit v
JOIN dwd.dwd_diagnosis diag ON v.visit_id = diag.visit_id
WHERE v.visit_type = '住院'
  AND diag.diagnosis_code LIKE 'C34%'
  AND diag.diagnosis_type = '主诊断'
  AND DATE_FORMAT(v.visit_date, '%Y-%m') = DATE_FORMAT(NOW(), '%Y-%m')
LIMIT 1;
```

## 数据质量风险

1. **mpi_id 覆盖率**：mpi 未关联成功的患者按 mpi_id 去重会低估患者数
2. **visit_type 标准化**：不同来源系统的住院/门诊标识可能不一致（如"IN"/"住院"/"1"）
3. **时区问题**：visit_date 跨零点就诊可能归入不同日期
4. **多院区合并**：多院区场景需确认是否要跨院区统计

## 示例问题
- 本月住院患者多少人
- 2025 年每个月门诊患者数趋势
- 肺癌患者住院人次是多少
- 各科室患者数排名
- 本月与上月患者数对比
