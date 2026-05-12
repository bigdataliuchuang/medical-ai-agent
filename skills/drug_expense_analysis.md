# Skill: 药品费用分析

## 适用场景
用户询问药品费用相关问题，包括：药品总费用、费用占比、科室费用排名、药品费用环比/同比、费用结构分析。
触发关键词：药品费用、药费、费用分析、费用占比、费用排名、费用趋势、费用结构。

## 业务口径

### 费用口径
| 口径 | 说明 | 数据来源 |
|------|------|----------|
| 医嘱费用 | 开立时费用，含退药 | dwd_order.drug_expense |
| 收费费用 | 实际收费，扣除退药 | dwd_expense_detail WHERE expense_category='DRUG' |
| 结算费用 | 含医保分割 | 需关联结算表（本项目暂不覆盖）|

**推荐使用收费费用**（dwd_expense_detail），更准确反映实际支出。

### 药费占比计算
```
药费占比 = 药品费用 / 总费用 × 100%
```
总费用包括：诊疗费、药品费、检查费、手术费、材料费。

### 环比增长率
```
环比增长率 = (本月费用 - 上月费用) / 上月费用 × 100%
```

## 推荐使用表

| 优先级 | 表名 | 用途 |
|--------|------|------|
| 首选 | `ads.ads_expense_by_tumor_type` | 按瘤种的费用汇总 |
| 首选 | `dws.dws_expense_summary_1d` | 日粒度费用汇总，含药费/总费用 |
| 明细 | `dwd.dwd_expense_detail` | 费用明细，最细粒度 |
| 字典 | `dim.dim_drug_dict` | 药品信息 |
| 字典 | `dim.dim_dept_dict` | 科室信息 |

## 常见 SQL 模板

### 模板1：按科室统计本月住院费用总额和药费占比
```sql
SELECT
    d.dept_name,
    SUM(e.expense_amount)  AS total_expense,
    SUM(CASE WHEN e.expense_category = 'DRUG' THEN e.expense_amount ELSE 0 END) AS drug_expense,
    ROUND(SUM(CASE WHEN e.expense_category = 'DRUG' THEN e.expense_amount ELSE 0 END)
          * 100.0 / NULLIF(SUM(e.expense_amount), 0), 2) AS drug_rate
FROM dwd.dwd_expense_detail e
JOIN dim.dim_dept_dict d ON e.dept_code = d.dept_code
WHERE DATE_FORMAT(e.expense_date, '%Y-%m') = DATE_FORMAT(NOW(), '%Y-%m')
  AND e.visit_type = '住院'
GROUP BY d.dept_name
ORDER BY drug_expense DESC
LIMIT 20;
```

### 模板2：按瘤种统计费用结构
```sql
SELECT
    tumor_type,
    avg_expense_per_patient,
    drug_expense,
    stat_month
FROM ads.ads_expense_by_tumor_type
WHERE stat_month = DATE_FORMAT(NOW(), '%Y-%m')
ORDER BY drug_expense DESC
LIMIT 20;
```

### 模板3：抗肿瘤药物费用环比增长最高的科室
```sql
SELECT
    dept_name,
    this_month_expense,
    last_month_expense,
    ROUND((this_month_expense - last_month_expense) * 100.0
          / NULLIF(last_month_expense, 0), 2) AS mom_growth_rate
FROM (
    SELECT
        d.dept_name,
        SUM(CASE WHEN t.stat_month = DATE_FORMAT(NOW(),'%Y-%m')
                 THEN t.drug_expense_total ELSE 0 END) AS this_month_expense,
        SUM(CASE WHEN t.stat_month = DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 1 MONTH),'%Y-%m')
                 THEN t.drug_expense_total ELSE 0 END) AS last_month_expense
    FROM dws.dws_tumor_drug_usage_1d t
    JOIN dim.dim_dept_dict d ON t.dept_code = d.dept_code
    WHERE t.stat_month >= DATE_FORMAT(DATE_SUB(NOW(), INTERVAL 1 MONTH), '%Y-%m')
    GROUP BY d.dept_name
) sub
ORDER BY mom_growth_rate DESC
LIMIT 10;
```

## 数据质量风险
1. **退药处理**：dwd_order 中退药未扣除会高估药品费用
2. **费用类别标准化**：不同来源系统的 expense_category 编码可能不同
3. **分摊费用**：部分费用（如手术间费）可能按患者分摊，需确认口径

## 示例问题
- 按科室统计本月住院药费占比
- 抗肿瘤药物费用环比增长最高的科室
- 按瘤种统计本月费用结构
- 药品费用最高的 TOP 10 科室
