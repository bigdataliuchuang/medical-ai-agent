# Skill: SQL 优化建议

## 适用场景
用户询问 SQL 性能问题、查询优化、Doris 执行计划、分区裁剪、聚合下推等。
触发关键词：SQL 慢、查询慢、优化、性能、索引、分区、执行计划、超时、OOM。

## 业务口径

### Doris 常见优化方向
1. **分区裁剪**：确保 WHERE 中有分区键（visit_date / stat_month）
2. **Bucket 裁剪**：WHERE 中包含 Bucket 列（mpi_id / dept_code）可大幅减少扫描
3. **聚合下推**：COUNT(DISTINCT ...) 在大表上很慢，优先用 ADS/DWS 汇总表
4. **JOIN 顺序**：大表在左，小表（字典表）在右；字典表尽量放 Broadcast
5. **避免 SELECT \***：只查需要的字段，减少网络传输

### 医疗场景常见慢查询原因
| 原因 | 解决方案 |
|------|----------|
| 无时间范围过滤 | 加 visit_date / stat_month 过滤 |
| COUNT(DISTINCT mpi_id) 全表扫 | 用汇总表或预计算 |
| 多大表 JOIN | 改用宽表或先聚合再 JOIN |
| SELECT * 导致传输量大 | 明确列出需要的字段 |
| 子查询嵌套过深 | 改为 WITH (CTE) |

## 常见 SQL 优化模板

### 优化前（慢）
```sql
-- 全表扫描，无分区裁剪
SELECT COUNT(DISTINCT mpi_id) FROM dwd.dwd_visit;
```

### 优化后（快）
```sql
-- 加时间范围，命中分区
SELECT COUNT(DISTINCT mpi_id)
FROM dwd.dwd_visit
WHERE visit_date >= '2025-01-01'
  AND visit_date < '2025-02-01';
```

### 使用 CTE 替代嵌套子查询
```sql
-- 推荐写法
WITH monthly_patient AS (
    SELECT mpi_id, dept_code, DATE_FORMAT(visit_date, '%Y-%m') AS stat_month
    FROM dwd.dwd_visit
    WHERE visit_date >= '2025-01-01'
)
SELECT dept_code, COUNT(DISTINCT mpi_id) AS patient_cnt
FROM monthly_patient
GROUP BY dept_code
LIMIT 20;
```

## 示例问题
- 这个 SQL 为什么跑得很慢
- COUNT DISTINCT 有什么优化方法
- Doris 查询如何使用分区裁剪
- 多张大表 JOIN 怎么优化
