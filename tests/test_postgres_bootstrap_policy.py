from control_plane_service import core


def test_postgres_runtime_never_executes_ddl(monkeypatch):
    calls=[]
    class Row(dict): pass
    class FakeDb:
        def __enter__(self): return self
        def __exit__(self,*_): pass
        def execute(self,sql,params=()):
            calls.append(sql)
            return type("Cursor",(),{"fetchone":lambda self:Row(present="events")})()
        def executescript(self,_): raise AssertionError("runtime DDL is forbidden")
    store=core.Store.__new__(core.Store); store.path="unused"; store.connect=lambda:FakeDb()
    monkeypatch.setattr(core,"is_postgres",lambda:True)
    store.initialize()
    assert calls[0].startswith("SELECT to_regclass")
    assert all(not sql.lstrip().upper().startswith("CREATE") for sql in calls)
