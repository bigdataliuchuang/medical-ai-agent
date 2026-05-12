import os
import sqlglot
from sqlglot import exp

# SQL_WHITELIST_TABLES 是一个环境变量，用来配置“允许查询的表”。
# 如果没有配置环境变量，就使用下面这一串默认表名。
# split(",") 会把字符串按逗号拆开，set(...) 会转成集合，方便后面判断表名是否允许。
WHITELIST = set(
    os.getenv(
        "SQL_WHITELIST_TABLES",
        "ads_dq_result_summary,ads_patient_mpi_summary,ads_drug_usage_trend,"
        "ads_tumor_report_monthly,ads_expense_by_tumor_type,ads_inpatient_quality_board,"
        "dq_check_result,dq_issue_detail,mpi_cross_reference",
    ).split(",")
)

# sqlglot 会把 SQL 解析成一棵语法树。
# 下面这些类型表示写入或修改数据库的操作，例如 INSERT、UPDATE、DELETE、DROP 等。
# 不同 sqlglot 版本暴露的 DDL 节点名略有差异，所以这里按名称安全收集。
FORBIDDEN_TYPES = tuple(
    node_type
    for node_name in ("Insert", "Update", "Delete", "Drop", "Alter", "Create", "TruncateTable")
    if (node_type := getattr(exp, node_name, None)) is not None
)

# 这里是字符串级别的快速检查。
# 只要 SQL 文本里出现这些危险关键字，就先拒绝。
FORBIDDEN_KEYWORDS = {"insert", "update", "delete", "drop", "truncate", "alter", "create"}

# 默认最多查询 100 条。
# 注意：这个值本身不会自动生效，只有调用 add_limit(sql) 时才会被加到 SQL 里。
DEFAULT_LIMIT = 100


def validate(sql: str) -> dict:
    """检查一条 SQL 是否安全。

    返回格式：
    - {"valid": True, "reason": ""} 表示可以执行
    - {"valid": False, "reason": "..."} 表示不允许执行，并说明原因
    """
    # 去掉 SQL 前后的空格，并去掉末尾的分号。
    # 例如 " select a from t; " 会变成 "select a from t"。
    sql_stripped = sql.strip().rstrip(";")

    # 拒绝多语句。
    # 如果中间还有分号，说明可能传入了多条 SQL，例如：
    # SELECT name FROM table1; DROP TABLE table1
    if ";" in sql_stripped:
        return {"valid": False, "reason": "禁止执行多条 SQL 语句"}

    # 先把 SQL 转成小写，方便检查关键字。
    # 比如 "DELETE"、"delete"、"Delete" 都会变成 "delete"。
    lower = sql_stripped.lower()
    for word in FORBIDDEN_KEYWORDS:
        # lower.startswith(word)：防止 SQL 一开头就是 delete/update/drop 等操作。
        # f" {word} " in lower：防止危险关键字出现在 SQL 中间。
        if lower.startswith(word) or f" {word} " in lower:
            return {"valid": False, "reason": f"禁止执行 {word.upper()} 操作"}

    # 使用 SQLGlot 解析 SQL。
    # parse_one 会把 SQL 文本解析成语法树 ast，后面可以从语法树里找表名、字段、LIMIT 等。
    try:
        ast = sqlglot.parse_one(sql_stripped, read="mysql")
    except Exception:
        return {"valid": False, "reason": "SQL 语法解析失败"}

    # 检查语法树里是否包含写操作节点。
    # ast.walk() 会遍历 SQL 里的所有语法节点。
    for node in ast.walk():
        if isinstance(node, FORBIDDEN_TYPES):
            return {"valid": False, "reason": f"禁止执行写操作"}

    # 禁止 SELECT *。
    # exp.Star 表示 SQL 里的星号 *。
    # 要求必须明确写字段名，例如 SELECT patient_id, patient_name FROM ...
    for node in ast.find_all(exp.Star):
        if not node.args.get("except"):
            return {"valid": False, "reason": "禁止 SELECT *，请指定具体字段"}

    # 提取 SQL 中用到的所有表名。
    # exp.Table 表示 SQL 里的表，例如 FROM ads_patient_mpi_summary。
    tables = set()
    for table in ast.find_all(exp.Table):
        name = table.name
        tables.add(name)

    # unknown 表示“不在白名单里的表”。
    # 只要 SQL 查询了一个没被允许的表，就拒绝。
    unknown = tables - WHITELIST
    if unknown:
        return {"valid": False, "reason": f"表 {', '.join(unknown)} 不在白名单中"}

    # 走到这里，说明 SQL 通过了所有安全检查。
    return {"valid": True, "reason": ""}


def add_limit(sql: str) -> str:
    """如果 SQL 没有 LIMIT 子句，自动加上 LIMIT 100。

    重点：
    - DEFAULT_LIMIT = 100 定义了默认限制数量
    - ast.limit(DEFAULT_LIMIT) 才是真正把 LIMIT 100 加到 SQL 里的地方
    - validate(sql) 只负责检查安全，不会自动添加 LIMIT
    """
    try:
        # 先把 SQL 解析成语法树，方便判断它有没有 LIMIT。
        ast = sqlglot.parse_one(sql.strip().rstrip(";"), read="mysql")
    except Exception:
        # 如果 SQL 解析失败，就原样返回。
        # 实际使用时，通常应该先调用 validate(sql)，通过后再调用 add_limit(sql)。
        return sql

    # 如果 SQL 已经有 LIMIT，就不重复添加。
    # 例如 SELECT id FROM table LIMIT 20 会原样返回。
    if ast.find(exp.Limit):
        return sql

    # 这里是真正添加 LIMIT 100 的地方。
    # DEFAULT_LIMIT 的值是 100，所以这行等价于给 SQL 加上 LIMIT 100。
    limited = ast.limit(DEFAULT_LIMIT)

    # 把修改后的语法树重新转回 MySQL 风格的 SQL 字符串。
    return limited.sql(dialect="mysql")
