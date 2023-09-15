import os
import yaml

is_prod = os.environ.get('IS_PROD')

config_file_name = 'config.prod.yaml'
if not is_prod:
    config_file_name = os.environ.get('CONFIG_FILE_NAME') or 'config.dev.yml'

config_file = os.path.join(os.path.dirname(__file__), config_file_name)

if 'CONFIG' not in globals():
    with open(config_file) as f:
        CONFIG: dict = yaml.safe_load(f)
    import logging.config
    logging.config.dictConfig(CONFIG['logging'])
