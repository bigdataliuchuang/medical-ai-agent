# Skill: 抗肿瘤药物使用分析

## 适用场景
用户询问抗肿瘤药物的使用情况，包括：使用患者数、使用金额、药品分布、科室分布、月度趋势等。
触发关键词：抗肿瘤、肿瘤药、靶向药、免疫药、化疗药、生物制剂、抗癌药。

## 输入参数
- 时间范围（必填）：stat_month / stat_date，如"本月"、"2025年1月"、"最近3个月"
- 瘤种（可选）：如肺癌(C34)、乳腺癌(C50)、结直肠癌(C18)
- 科室（可选）：dept_code / dept_name
- 药品（可选）：drug_code / drug_name / drug_category

## 业务口径

### 抗肿瘤药物认定规则
1. 使用 dim.dim_drug_dict 表，过滤 `drug_category = 'ANTITUMOR'`
2. 或按 ATC 分类：L01（抗肿瘤药）、L02（内分泌治疗）、L03（免疫调节剂）

### 患者去重规则
- 统计使用患者数时，必须按 mpi_id 去重（`COUNT(DISTINCT mpi_id)`）
- 不能用 visit_id 代替（同一患者多次就诊会重复计数）

### 费用口径
- 药品费用取 dwd_expense_detail.expense_amount，过滤 `expense_category = 'DRUG'`
- 或取 dwd_order.drug_expense（医嘱层面费用，含退药可能，需排除 order_status = 'CANCELLED'）

### 时间范围
- ADS 汇总表（ads_drug_usage_trend）按 stat_month 统计，格式为 'YYYY-MM'
- DWD 明细表按 visit_date 或 order_date 过滤，需带索引字段

## 推荐使用表

| 优先级 | 表名 | 用途 |
|--------|------|------|
| 首选 | `ads.ads_drug_usage_trend` | 月度汇总，已聚合，查询快 |
| 首选 | `dws.dws_tumor_drug_usage_1d` | 日粒度汇总，支持科室/药品维度 |
| 明细 | `dwd.dwd_order` | 医嘱明细，支持单患者追踪 |
| 明细 | `dwd.dwd_expense_detail` | 费用明细，最细粒度 |
| 字典 | `dim.dim_drug_dict` | 药品分类、ATC码、是否抗肿瘤 |
| 字典 | `dim.dim_dept_dict` | 科室编码与名称映射 |
| 字典 | `dim.dim_diagnosis_dict` | ICD-10 诊断编码与瘤种映射 |

## 执行步骤

1. **确认时间范围**：从问题中提取时间，转换为 stat_month（如"本月"→当前年月）
2. **确认药品范围**：是否限定具体药品或瘤种，查 dim_drug_dict / dim_diagnosis_dict
3. **选择表**：汇总分析用 ads/dws 表；明细追踪用 dwd 表
4. **患者去重**：COUNT(DISTINCT mpi_id)
5. **关联维度**：科室信息关联 dim_dept_dict；药品信息关联 dim_drug_dict
6. **输出风险提示**：数据来源、去重口径、时间范围、排除逻辑

## 常见 SQL 模板

### 模板1：本月各科室抗肿瘤药物使用患者数
```sql
SELECT
    d.dept_name,
    COUNT(DISTINCT t.mpi_id) AS patient_cnt,
    SUM(t.drug_expense_total)  AS drug_expense
FROM dws.dws_tumor_drug_usage_1d t
JOIN dim.dim_dept_dict d ON t.dept_code = d.dept_code
WHERE t.stat_month = DATE_FORMAT(NOW(), '%Y-%m')
GROUP BY d.dept_name
ORDER BY patient_cnt DESC
LIMIT 20;
```

### 模板2：肺癌患者抗肿瘤药物费用按月趋势
```sql
SELECT
    stat_month,
    SUM(drug_expense_total) AS monthly_expense,
    COUNT(DISTINCT mpi_id)  AS patient_cnt
FROM ads.ads_drug_usage_trend
WHERE tumor_type = 'lung'
  AND stat_month >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 6 MONTH), '%Y-%m')
GROUP BY stat_month
ORDER BY stat_month
LIMIT 12;
```

### 模板3：抗肿瘤药物使用金额 TOP 10 药品
```sql
SELECT
    dr.drug_name,
    dr.drug_category,
    SUM(t.drug_expense_total) AS total_expense,
    COUNT(DISTINCT t.mpi_id) AS patient_cnt
FROM dws.dws_tumor_drug_usage_1d t
JOIN dim.dim_drug_dict dr ON t.drug_code = dr.drug_code
WHERE t.stat_month = DATE_FORMAT(NOW(), '%Y-%m')
GROUP BY dr.drug_name, dr.drug_category
ORDER BY total_expense DESC
LIMIT 10;
```

## 数据质量风险

1. **药品字典未覆盖**：部分新上市药品可能不在 dim_drug_dict 的 ANTITUMOR 分类中
2. **退药未排除**：dwd_order 中 order_status = 'CANCELLED' 的记录需过滤
3. **mpi_id 为空**：mpi 未关联成功的患者无法去重，需先检查 mpi 覆盖率
4. **跨院区数据**：多院区场景下 dept_code 可能重复，需加 hospital_code 区分
5. **费用口径不一致**：医嘱费用 vs 结算费用 vs 实际收费，需与业务方确认

## 示例问题
- 统计 2025 年每个月抗肿瘤药物使用患者数
- 本月各科室抗肿瘤药物费用是多少
- 肺癌患者中使用免疫药物的人数
- 抗肿瘤药物使用金额 TOP 10 药品
- 本月抗肿瘤药物费用环比上月增长多少
