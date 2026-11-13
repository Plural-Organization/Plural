import importlib
import os

active = importlib.import_module(f"config.{os.environ.get('APP_ENV', 'production')}")
