# Skill: DWD 建模辅助

## 适用场景
用户询问 DWD 明细层的表设计、字段含义、建模规范、表关联关系。
触发关键词：DWD、建模、表设计、字段定义、明细层、数据分层、ODS、DWS、表结构。

## 业务口径

### 数据分层规范
| 层次 | 说明 | 代表表 |
|------|------|--------|
| ODS | 原始数据，1:1同步 | ods_inpatient_order |
| DWD | 明细层，标准化清洗 | dwd_visit, dwd_diagnosis, dwd_order |
| DWS | 汇总层，按主题聚合 | dws_tumor_drug_usage_1d |
| ADS | 应用层，面向报表 | ads_drug_usage_trend |

### DWD 核心表关系
```
dwd_patient (mpi_id) ← 主患者表
    ↓ 1:N
dwd_visit (visit_id, mpi_id) ← 就诊表
    ↓ 1:N                    ↓ 1:N
dwd_diagnosis              dwd_order
(visit_id, diagnosis_code)  (visit_id, drug_code)
                                ↓ 1:N
                            dwd_expense_detail
                            (visit_id, order_id)
```

### 关键字段规范
| 字段 | 说明 | 注意事项 |
|------|------|----------|
| mpi_id | 主索引患者ID | 全院唯一，用于患者去重 |
| visit_id | 就诊ID | 一次住院或门诊的唯一标识 |
| visit_sn | 就诊流水号 | 来自HIS的原始编号，可能重复 |
| drug_code | 药品编码 | 需关联 dim_drug_dict 获取药品名称 |
| diagnosis_code | 诊断编码 | ICD-10 格式 |
| dept_code | 科室编码 | 需关联 dim_dept_dict |

## 推荐建模要点

1. **时间分区**：DWD 表必须有日期分区字段（visit_date / order_date），避免全表扫描
2. **保留原始键**：保留 HIS 原始 ID（visit_sn）同时增加平台 ID（visit_id）
3. **标准化编码**：诊断、药品、科室全部关联字典表，不在事实表存文字
4. **mpi 关联**：所有事实表必须关联 mpi_id，支持患者级别分析

## 示例问题
- dwd_visit 和 dwd_diagnosis 怎么关联
- visit_id 和 visit_sn 的区别是什么
- DWD 层为什么要用 mpi_id 而不是 patient_id
- 如何设计抗肿瘤药物使用的 DWD 明细表
