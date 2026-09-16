"""
Full template validator — uses the same filters and globals that main.py registers,
so this is the definitive pass/fail: if this says OK, the server will too.
"""
import json, os
from datetime import datetime
from jinja2 import Environment, FileSystemLoader, TemplateSyntaxError, UndefinedError

env = Environment(loader=FileSystemLoader("app/templates"), undefined=UndefinedError)

def label(v):
    if not v: return "-"
    return str(v).replace("_", " ").title()

def _fmt_dt(value, fmt="%d %b %Y %H:%M"):
    if not value: return "-"
    if isinstance(value, datetime): return value.strftime(fmt)
    try: return datetime.fromisoformat(str(value)).strftime(fmt)
    except: return str(value)

env.filters["label"]    = label
env.filters["dt"]       = lambda v: _fmt_dt(v, "%d %b %Y %H:%M")
env.filters["d"]        = lambda v: _fmt_dt(v, "%d %b %Y")
env.filters["fromjson"] = lambda v: json.loads(v or "[]")
env.filters["tojson"]   = lambda v: json.dumps(v)
env.globals["dict"]     = dict

errors   = []
warnings = []
ok_count = 0

for root, dirs, files in os.walk("app/templates"):
    for f in sorted(files):
        if not f.endswith(".html"):
            continue
        path = os.path.relpath(os.path.join(root, f), "app/templates").replace("\\", "/")
        try:
            env.get_template(path)
            print(f"  OK   {path}")
            ok_count += 1
        except TemplateSyntaxError as e:
            msg = f"  SYNTAX ERROR  {path}:{e.lineno}: {e.message}"
            errors.append(msg)
            print(msg)
        except Exception as e:
            msg = f"  ERROR  {path}: {e}"
            errors.append(msg)
            print(msg)

print(f"\n{'='*55}")
print(f"  Templates OK:     {ok_count}")
print(f"  Errors:           {len(errors)}")
if errors:
    print("\nFailed templates:")
    for e in errors:
        print(" ", e)
    import sys; sys.exit(1)
else:
    print("  ALL TEMPLATES PASS")
