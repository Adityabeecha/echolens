"""API routes, one module per area, each an APIRouter included by app.py.

app.py grew to 5,000+ lines with every endpoint in it. New areas go here, and
an existing area moves here when it is next changed substantially. Rule for a
move: tests patch some of app.py's internals (the background runners such as
_run_investigation_bg); a route that calls one of those keeps calling it as
`app_module._name(...)` at call time, or stays in app.py, so the patch still
takes effect.
"""
