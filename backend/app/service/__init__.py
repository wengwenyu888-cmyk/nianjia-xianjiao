"""业务逻辑层：事务边界、幂等、状态机都在这里。

铁律：跨表写操作必须在一个 service 方法内完成；service 不感知 HTTP（不抛 HTTPException）。
"""
