import importlib.util
import json
spec = importlib.util.spec_from_file_location('pattern_stocks_mod', 'c:/Users/prave/OneDrive/Desktop/Python/pattern_stocks.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
res = mod.compute_daily_movers_all(top_n=5, chunk_size=100)
print(json.dumps(res, indent=2))
