# Skill: 检验异常分析

## 适用场景
用户询问检验结果的异常情况，包括：异常指标数量、异常率、危急值、特定指标的异常分布。
触发关键词：检验异常、检验结果、危急值、异常指标、化验、实验室、检验报告。

## 业务口径

### 异常判断规则
1. result_flag IN ('H', 'L', 'HH', 'LL', 'A')（高/低/极高/极低/异常）
2. 数值结果 > reference_high 或 < reference_low
3. result_status = 'ABNORMAL'

### 危急值定义
result_flag IN ('HH', 'LL') 或 is_critical_value = 1。

## 推荐使用表

| 表名 | 用途 |
|------|------|
| `dwd.dwd_lab_result` | 检验结果明细 |
| `dim.dim_lab_item_dict` | 检验项目字典（含参考范围） |
| `dwd.dwd_visit` | 关联就诊信息 |

## 常见 SQL 模板

### 模板1：本月检验异常结果数量及异常率
```sql
SELECT
    COUNT(*) AS total_results,
    SUM(CASE WHEN result_flag IN ('H','L','HH','LL','A') THEN 1 ELSE 0 END) AS abnormal_cnt,
    ROUND(SUM(CASE WHEN result_flag IN ('H','L','HH','LL','A') THEN 1 ELSE 0 END)
          * 100.0 / COUNT(*), 2) AS abnormal_rate
FROM dwd.dwd_lab_result
WHERE DATE_FORMAT(result_date, '%Y-%m') = DATE_FORMAT(NOW(), '%Y-%m')
LIMIT 1;
```

### 模板2：危急值数量（按检验项目）
```sql
SELECT
    li.item_name,
    COUNT(*) AS critical_cnt
FROM dwd.dwd_lab_result lr
JOIN dim.dim_lab_item_dict li ON lr.item_code = li.item_code
WHERE lr.result_flag IN ('HH', 'LL')
  AND lr.result_date >= DATE_FORMAT(NOW(), '%Y-%m-01')
GROUP BY li.item_name
ORDER BY critical_cnt DESC
LIMIT 20;
```

## 数据质量风险
1. **参考范围不统一**：不同仪器或年龄段的参考范围不同，需结合 dim_lab_item_dict
2. **文本结果无法数值化**：部分定性检验（如阴性/阳性）需单独处理
3. **结果回报延迟**：检验结果可能 T+1 才入库

## 示例问题
- 本月检验异常结果数量是多少
- 危急值数量最多的检验项目
- 肿瘤患者检验异常率是多少
